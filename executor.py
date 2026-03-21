"""
Trade executor — submits orders to Alpaca and manages stop-loss / take-profit.

Supports both long (buy) and short (sell) positions.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
    TrailingStopOrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType

import config

logger = logging.getLogger(__name__)


# ─── Client singleton ─────────────────────────────────────────────────────────

def get_trading_client() -> TradingClient:
    return TradingClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
        paper=("paper" in config.ALPACA_BASE_URL),
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def is_shortable(symbol: str, trading_client: Optional[TradingClient] = None) -> bool:
    """
    Returns True only if the asset is both shortable and easy-to-borrow on Alpaca.
    Requires a margin account.
    """
    client = trading_client or get_trading_client()
    try:
        asset = client.get_asset(symbol)
        return bool(asset.shortable and asset.easy_to_borrow)
    except Exception as exc:
        logger.error("Could not check shortability for %s: %s", symbol, exc)
        return False


def calculate_shares(
    portfolio_value: float,
    current_price: float,
    position_size_modifier: float = 1.0,
) -> int:
    """
    Compute number of whole shares based on MAX_POSITION_SIZE and modifier.
    """
    max_dollars = portfolio_value * config.MAX_POSITION_SIZE * position_size_modifier
    shares = int(max_dollars / current_price)
    return max(shares, 1)


def _wait_for_fill(
    order_id: str,
    trading_client: TradingClient,
    timeout_seconds: int = 30,
    poll_interval: float = 1.0,
) -> Optional[float]:
    """
    Poll until an order is filled or timeout. Returns the average fill price.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            order = trading_client.get_order_by_id(order_id)
            if order.status.value == "filled":
                return float(order.filled_avg_price)
            if order.status.value in ("canceled", "expired", "rejected"):
                logger.warning("Order %s ended with status %s", order_id, order.status)
                return None
        except Exception as exc:
            logger.error("Error polling order %s: %s", order_id, exc)
        time.sleep(poll_interval)
    logger.warning("Order %s not filled within %ds", order_id, timeout_seconds)
    return None


# ─── Long trades ──────────────────────────────────────────────────────────────

def execute_long(
    symbol: str,
    shares: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    trading_client: Optional[TradingClient] = None,
) -> dict:
    """
    Opens a long (buy) position via a market order, then places
    stop-loss and take-profit bracket orders once the fill price is known.
    """
    client = trading_client or get_trading_client()

    order_req = MarketOrderRequest(
        symbol=symbol,
        qty=shares,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )

    logger.info("Submitting LONG market order: %s x%d", symbol, shares)
    submitted = client.submit_order(order_req)
    order_id = str(submitted.id)
    logger.info("Long order submitted — id=%s", order_id)

    fill_price = _wait_for_fill(order_id, client)
    if fill_price is None:
        logger.error("Long order %s did not fill; skipping bracket orders", order_id)
        return {"order": submitted, "fill_price": None, "stop": None, "target": None}

    stop_price = round(fill_price * (1 - stop_loss_pct), 4)
    target_price = round(fill_price * (1 + take_profit_pct), 4)

    stop_order = _place_stop(client, symbol, shares, stop_price, OrderSide.SELL)
    target_order = _place_limit(client, symbol, shares, target_price, OrderSide.SELL)

    logger.info(
        "LONG %s filled @ %.4f | stop=%.4f | target=%.4f",
        symbol, fill_price, stop_price, target_price,
    )

    return {
        "order": submitted,
        "fill_price": fill_price,
        "stop": stop_order,
        "target": target_order,
        "direction": "long",
    }


# ─── Short trades ─────────────────────────────────────────────────────────────

def execute_short(
    symbol: str,
    shares: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    trading_client: Optional[TradingClient] = None,
) -> dict:
    """
    Opens a short position via Alpaca (requires a margin account).

    For shorts:
      Stop loss  is ABOVE entry price (price rising = loss).
      Take profit is BELOW entry price (price falling = profit).
    """
    client = trading_client or get_trading_client()

    order_req = MarketOrderRequest(
        symbol=symbol,
        qty=shares,
        side=OrderSide.SELL,       # SELL to open short
        time_in_force=TimeInForce.DAY,
    )

    logger.info("Submitting SHORT market order: %s x%d", symbol, shares)
    submitted = client.submit_order(order_req)
    order_id = str(submitted.id)
    logger.info("Short order submitted — id=%s", order_id)

    fill_price = _wait_for_fill(order_id, client)
    if fill_price is None:
        logger.error("Short order %s did not fill; skipping bracket orders", order_id)
        return {"order": submitted, "fill_price": None, "stop": None, "target": None}

    # Stop loss above entry; take profit below entry
    stop_price = round(fill_price * (1 + stop_loss_pct), 4)
    target_price = round(fill_price * (1 - take_profit_pct), 4)

    stop_order = _place_stop(client, symbol, shares, stop_price, OrderSide.BUY)
    target_order = _place_limit(client, symbol, shares, target_price, OrderSide.BUY)

    logger.info(
        "SHORT %s filled @ %.4f | stop=%.4f | target=%.4f",
        symbol, fill_price, stop_price, target_price,
    )

    return {
        "order": submitted,
        "fill_price": fill_price,
        "stop": stop_order,
        "target": target_order,
        "direction": "short",
    }


def close_short(symbol: str, trading_client: Optional[TradingClient] = None) -> None:
    """
    Close an open short position (Alpaca handles long/short correctly).
    """
    client = trading_client or get_trading_client()
    try:
        client.close_position(symbol)
        logger.info("Closed position in %s", symbol)
    except Exception as exc:
        logger.error("Failed to close position in %s: %s", symbol, exc)
        raise


# ─── Orphan-order cleanup ─────────────────────────────────────────────────────

def cancel_orders_for_symbol(symbol: str, trading_client: TradingClient) -> None:
    """
    Cancel any open orders for a symbol before entering a new position.

    When a bracket fires (stop or take-profit), Alpaca closes the position but
    leaves the sibling GTC order open. These orphaned orders accumulate and
    deplete buying_power, shrinking subsequent position sizes. Cancelling them
    before each new entry keeps buying_power accurate.
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        open_orders = trading_client.get_orders(
            filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        )
        for order in open_orders:
            try:
                trading_client.cancel_order_by_id(str(order.id))
                logger.info("Cancelled orphaned order %s for %s", order.id, symbol)
            except Exception as exc:
                logger.warning("Could not cancel order %s for %s: %s", order.id, symbol, exc)
    except Exception as exc:
        logger.warning("Could not fetch open orders for %s: %s", symbol, exc)


# ─── Unified entry point ──────────────────────────────────────────────────────

def execute_trade(
    symbol: str,
    decision: dict,
    portfolio_value: float,
    current_price: float,
    trading_client: Optional[TradingClient] = None,
) -> Optional[dict]:
    """
    Routes to execute_long() or execute_short() based on decision["action"].
    Returns the execution result dict, or None if action is 'hold'.
    """
    action = decision.get("action", "hold")
    if action == "hold":
        logger.info("Action=hold for %s — no order submitted", symbol)
        return None

    stop_loss_pct = float(decision.get("stop_loss_pct", config.STOP_LOSS_PCT))
    take_profit_pct = float(decision.get("take_profit_pct", config.TAKE_PROFIT_PCT))
    modifier = float(decision.get("position_size_modifier", 1.0))

    client = trading_client or get_trading_client()

    cancel_orders_for_symbol(symbol, client)

    shares = calculate_shares(portfolio_value, current_price, modifier)

    if action == "buy":
        return execute_long(symbol, shares, stop_loss_pct, take_profit_pct, client)
    elif action == "sell":
        return execute_short(symbol, shares, stop_loss_pct, take_profit_pct, client)
    else:
        logger.warning("Unknown action '%s' for %s — holding", action, symbol)
        return None


# ─── Internal order helpers ───────────────────────────────────────────────────

_BRACKET_RETRIES: int = 3       # max attempts for stop/limit bracket orders
_BRACKET_RETRY_DELAY: float = 2.0  # seconds between retries (multiplied by attempt #)


def _place_stop(
    client: TradingClient,
    symbol: str,
    qty: int,
    stop_price: float,
    side: OrderSide,
) -> Optional[object]:
    """
    Place a GTC stop order with retry logic.

    Alpaca occasionally rejects bracket orders immediately after the entry fill
    because the position hasn't propagated to their order management system yet.
    Retrying with a short back-off resolves this in practice.
    """
    for attempt in range(1, _BRACKET_RETRIES + 1):
        try:
            req = StopOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.GTC,
                stop_price=stop_price,
            )
            order = client.submit_order(req)
            if attempt > 1:
                logger.info(
                    "Stop order for %s placed on attempt %d", symbol, attempt
                )
            return order
        except Exception as exc:
            if attempt < _BRACKET_RETRIES:
                logger.warning(
                    "Stop order attempt %d/%d failed for %s @ %.4f: %s — retrying in %.0fs",
                    attempt, _BRACKET_RETRIES, symbol, stop_price, exc,
                    attempt * _BRACKET_RETRY_DELAY,
                )
                time.sleep(attempt * _BRACKET_RETRY_DELAY)
            else:
                logger.error(
                    "Stop order failed after %d attempts for %s @ %.4f: %s — "
                    "position is UNPROTECTED; EOD liquidation is the only stop",
                    _BRACKET_RETRIES, symbol, stop_price, exc,
                )
    return None


def _place_limit(
    client: TradingClient,
    symbol: str,
    qty: int,
    limit_price: float,
    side: OrderSide,
) -> Optional[object]:
    """
    Place a GTC limit (take-profit) order with retry logic.
    """
    for attempt in range(1, _BRACKET_RETRIES + 1):
        try:
            req = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.GTC,
                limit_price=limit_price,
            )
            order = client.submit_order(req)
            if attempt > 1:
                logger.info(
                    "Limit order for %s placed on attempt %d", symbol, attempt
                )
            return order
        except Exception as exc:
            if attempt < _BRACKET_RETRIES:
                logger.warning(
                    "Limit order attempt %d/%d failed for %s @ %.4f: %s — retrying in %.0fs",
                    attempt, _BRACKET_RETRIES, symbol, limit_price, exc,
                    attempt * _BRACKET_RETRY_DELAY,
                )
                time.sleep(attempt * _BRACKET_RETRY_DELAY)
            else:
                logger.error(
                    "Limit order failed after %d attempts for %s @ %.4f: %s",
                    _BRACKET_RETRIES, symbol, limit_price, exc,
                )
    return None
