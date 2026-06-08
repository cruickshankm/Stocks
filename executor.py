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
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType, OrderClass

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
    current_price: float,
    trading_client: Optional[TradingClient] = None,
) -> dict:
    """
    Opens a long (buy) position via a single BRACKET market order with an
    attached take-profit (limit) and stop-loss (stop) as an OCO pair.

    Bracket levels are computed from current_price because Alpaca requires the
    TP/SL prices at submission time (before the market order fills). The market
    fill is essentially current_price for liquid symbols.
    """
    client = trading_client or get_trading_client()

    stop_price   = round(current_price * (1 - stop_loss_pct), 2)
    target_price = round(current_price * (1 + take_profit_pct), 2)

    order_req = MarketOrderRequest(
        symbol=symbol,
        qty=shares,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.GTC,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=target_price),
        stop_loss=StopLossRequest(stop_price=stop_price),
    )

    logger.info(
        "Submitting LONG bracket order: %s x%d | stop=%.2f | target=%.2f",
        symbol, shares, stop_price, target_price,
    )
    submitted = client.submit_order(order_req)
    order_id = str(submitted.id)
    logger.info("Long bracket order submitted — id=%s", order_id)

    fill_price = _wait_for_fill(order_id, client)
    if fill_price is None:
        logger.error("Long order %s did not fill", order_id)
        return {"order": submitted, "fill_price": None, "stop": None, "target": None}

    logger.info(
        "LONG %s filled @ %.4f | stop=%.2f | target=%.2f",
        symbol, fill_price, stop_price, target_price,
    )

    return {
        "order": submitted,
        "fill_price": fill_price,
        "stop": stop_price,
        "target": target_price,
        "direction": "long",
    }


# ─── Short trades ─────────────────────────────────────────────────────────────

def execute_short(
    symbol: str,
    shares: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    current_price: float,
    trading_client: Optional[TradingClient] = None,
) -> dict:
    """
    Opens a short position via a single BRACKET market order (requires a margin
    account). The take-profit (limit) and stop-loss (stop) are attached as an
    OCO pair so only one full-size closing order exists at a time.

    For shorts:
      Stop loss   is ABOVE entry price (price rising = loss).
      Take profit is BELOW entry price (price falling = profit).

    Bracket levels are computed from current_price because Alpaca requires them
    at submission time (before the market order fills).
    """
    client = trading_client or get_trading_client()

    stop_price   = round(current_price * (1 + stop_loss_pct), 2)
    target_price = round(current_price * (1 - take_profit_pct), 2)

    order_req = MarketOrderRequest(
        symbol=symbol,
        qty=shares,
        side=OrderSide.SELL,       # SELL to open short
        time_in_force=TimeInForce.GTC,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=target_price),
        stop_loss=StopLossRequest(stop_price=stop_price),
    )

    logger.info(
        "Submitting SHORT bracket order: %s x%d | stop=%.2f | target=%.2f",
        symbol, shares, stop_price, target_price,
    )
    submitted = client.submit_order(order_req)
    order_id = str(submitted.id)
    logger.info("Short bracket order submitted — id=%s", order_id)

    fill_price = _wait_for_fill(order_id, client)
    if fill_price is None:
        logger.error("Short order %s did not fill", order_id)
        return {"order": submitted, "fill_price": None, "stop": None, "target": None}

    logger.info(
        "SHORT %s filled @ %.4f | stop=%.2f | target=%.2f",
        symbol, fill_price, stop_price, target_price,
    )

    return {
        "order": submitted,
        "fill_price": fill_price,
        "stop": stop_price,
        "target": target_price,
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

    IMPORTANT: Only call this when opening a FRESH position (no existing holding).
    When pyramiding into an existing position use cancel_orphaned_orders_for_symbol()
    so that active stop/limit brackets protecting the existing position are preserved.
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


def cancel_orphaned_orders_for_symbol(symbol: str, trading_client: TradingClient) -> None:
    """
    Cancel only orphaned bracket orders for a symbol — i.e. stop/limit orders
    whose parent position no longer exists.

    Use this when PYRAMIDING (adding to an existing position) so that active
    stop-loss and take-profit orders protecting earlier entries are NOT cancelled.
    Only truly stale orders (e.g. from a previously closed position on the same
    symbol earlier in the session) are removed.
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus, OrderType

        # Check current position size
        try:
            position = trading_client.get_open_position(symbol)
            held_qty = abs(float(position.qty))
        except Exception:
            held_qty = 0.0

        open_orders = trading_client.get_orders(
            filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        )

        # Sum up qty covered by existing protective bracket orders
        bracket_qty = sum(
            float(o.qty)
            for o in open_orders
            if o.order_type in (OrderType.STOP, OrderType.LIMIT)
        )

        # If bracket qty exceeds current position qty, the excess is orphaned
        orphan_qty = max(0.0, bracket_qty - held_qty)
        if orphan_qty <= 0:
            logger.debug("No orphaned bracket orders found for %s", symbol)
            return

        cancelled = 0
        remaining_orphan = orphan_qty
        for order in open_orders:
            if remaining_orphan <= 0:
                break
            if order.order_type in (OrderType.STOP, OrderType.LIMIT):
                order_qty = float(order.qty)
                if order_qty <= remaining_orphan:
                    try:
                        trading_client.cancel_order_by_id(str(order.id))
                        logger.info(
                            "Cancelled orphaned bracket order %s (%s x%.0f) for %s",
                            order.id, order.order_type, order_qty, symbol,
                        )
                        remaining_orphan -= order_qty
                        cancelled += 1
                    except Exception as exc:
                        logger.warning(
                            "Could not cancel orphaned order %s for %s: %s",
                            order.id, symbol, exc,
                        )

        if cancelled:
            logger.info("Removed %d orphaned bracket order(s) for %s", cancelled, symbol)

    except Exception as exc:
        logger.warning("Could not check orphaned orders for %s: %s", symbol, exc)


# ─── Unified entry point ──────────────────────────────────────────────────────

def execute_trade(
    symbol: str,
    decision: dict,
    portfolio_value: float,
    current_price: float,
    trading_client: Optional[TradingClient] = None,
    existing_position: Optional[float] = None,
) -> Optional[dict]:
    """
    Routes to execute_long() or execute_short() based on decision["action"].
    Returns the execution result dict, or None if action is 'hold'.

    existing_position: current held qty (positive=long, negative=short, None/0=flat).
    When pyramiding into an existing position only orphaned brackets are removed so
    that active stop/limit orders protecting earlier entries are preserved.
    """
    action = decision.get("action", "hold")
    if action == "hold":
        logger.info("Action=hold for %s — no order submitted", symbol)
        return None

    stop_loss_pct = float(decision.get("stop_loss_pct", config.STOP_LOSS_PCT))
    take_profit_pct = float(decision.get("take_profit_pct", config.TAKE_PROFIT_PCT))
    modifier = float(decision.get("position_size_modifier", 1.0))

    client = trading_client or get_trading_client()

    is_pyramid = existing_position is not None and existing_position != 0
    if is_pyramid:
        logger.info(
            "Pyramiding into existing %s position (%.0f shares) — "
            "preserving active bracket orders, removing orphans only",
            symbol, existing_position,
        )
        cancel_orphaned_orders_for_symbol(symbol, client)
    else:
        cancel_orders_for_symbol(symbol, client)

    shares = calculate_shares(portfolio_value, current_price, modifier)

    if action == "buy":
        return execute_long(symbol, shares, stop_loss_pct, take_profit_pct, current_price, client)
    elif action == "sell":
        return execute_short(symbol, shares, stop_loss_pct, take_profit_pct, current_price, client)
    else:
        logger.warning("Unknown action '%s' for %s — holding", action, symbol)
        return None


# ─── Internal order helpers ───────────────────────────────────────────────────

_BRACKET_RETRIES: int = 3       # max attempts for stop/limit bracket orders
_BRACKET_RETRY_DELAY: float = 2.0  # seconds between retries (multiplied by attempt #)


def _place_trailing_stop(
    client: TradingClient,
    symbol: str,
    qty: int,
    trail_pct: float,
    side: OrderSide,
) -> Optional[object]:
    """
    Place a GTC trailing stop order with retry logic.

    trail_pct: fractional percentage trail, e.g. 0.05 for a 5% trail.
    Alpaca expects trail_percent as a plain number (5.0 = 5%).

    The trailing stop follows price in the favourable direction and only
    triggers when price reverses by trail_pct from the best price seen,
    locking in profits automatically as the trade moves in our favour.
    """
    trail_percent = round(trail_pct * 100, 2)
    for attempt in range(1, _BRACKET_RETRIES + 1):
        try:
            req = TrailingStopOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.GTC,
                trail_percent=trail_percent,
            )
            order = client.submit_order(req)
            if attempt > 1:
                logger.info(
                    "Trailing stop for %s placed on attempt %d (trail=%.1f%%)",
                    symbol, attempt, trail_percent,
                )
            return order
        except Exception as exc:
            if attempt < _BRACKET_RETRIES:
                logger.warning(
                    "Trailing stop attempt %d/%d failed for %s (trail=%.1f%%): %s "
                    "— retrying in %.0fs",
                    attempt, _BRACKET_RETRIES, symbol, trail_percent, exc,
                    attempt * _BRACKET_RETRY_DELAY,
                )
                time.sleep(attempt * _BRACKET_RETRY_DELAY)
            else:
                logger.error(
                    "Trailing stop failed after %d attempts for %s (trail=%.1f%%): %s — "
                    "position is UNPROTECTED; EOD liquidation is the only stop",
                    _BRACKET_RETRIES, symbol, trail_percent, exc,
                )
    return None


def _place_stop(
    client: TradingClient,
    symbol: str,
    qty: int,
    stop_price: float,
    side: OrderSide,
) -> Optional[object]:
    """
    Place a GTC fixed stop order with retry logic. Kept for reference/fallback;
    live entries now use _place_trailing_stop() instead.
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
