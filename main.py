"""
Main entry point for the AI trading bot.

Normal run:
    python main.py

Signal confirmation dry-run (no Claude, no orders):
    python main.py --confirm-test

Backtest:
    python main.py --backtest
    python main.py --backtest --symbol AAPL
    python main.py --backtest --symbol AAPL,MSFT --start 2024-01-01 --end 2024-12-31
    python main.py --backtest --symbol GLD --start 2024-06-01 --mode weighted

Options:
    --confirm-test        Print confirmation reports for all watchlist symbols and exit.
    --symbol TICKER[,...] Restrict to one or more symbols (comma-separated).
    --once                Run one scan cycle and exit (don't loop).
    --backtest            Run backtester and exit (no live trading).
    --start DATE          Backtest start date  (YYYY-MM-DD, default: 180 days ago).
    --end DATE            Backtest end date    (YYYY-MM-DD, default: yesterday).
    --capital FLOAT       Starting capital for backtest (default: 10000).
    --mode MODE           Override CONFIRMATION_MODE for backtest (strict|weighted).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

import config
import logger as db
from strategies import (
    get_macd_signal,
    get_vwap_signal,
    get_ema_signal,
    get_price_action_signal,
    evaluate_confirmation,
    get_trend_direction,
)
from claude_brain import get_trade_decision
from risk_gate import run_risk_gate
from executor import execute_trade, get_trading_client, calculate_shares
from dashboard import LiveDashboard, render_snapshot

# ─── Logging setup ────────────────────────────────────────────────────────────

from rich.logging import RichHandler
from dashboard import console as _dash_console

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(message)s",
    datefmt="%H:%M:%S",
    handlers=[RichHandler(console=_dash_console, show_path=False, rich_tracebacks=True)],
)
log = logging.getLogger("main")


# ─── Market data helpers ──────────────────────────────────────────────────────

# Data client created once at module level to avoid Rich Live rendering conflicts
from alpaca.data.historical import StockHistoricalDataClient as _StockDataClient
from alpaca.data.requests import StockBarsRequest as _StockBarsRequest
from alpaca.data.timeframe import TimeFrame as _TimeFrame, TimeFrameUnit as _TimeFrameUnit
from alpaca.data.enums import DataFeed as _DataFeed

_data_client: Optional[_StockDataClient] = None

def _get_data_client() -> _StockDataClient:
    global _data_client
    if _data_client is None:
        _data_client = _StockDataClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )
    return _data_client


def _get_bars(trading_client, symbol: str, timeframe: str = "1Hour", limit: int = 250) -> pd.DataFrame:
    """
    Fetch historical bars from Alpaca and return as a DataFrame with
    columns: open, high, low, close, volume, timestamp.
    """
    global _data_client

    _tf_map = {
        "1Min":  _TimeFrame(1,  _TimeFrameUnit.Minute),
        "5Min":  _TimeFrame(5,  _TimeFrameUnit.Minute),
        "15Min": _TimeFrame(15, _TimeFrameUnit.Minute),
        "1Hour": _TimeFrame(1,  _TimeFrameUnit.Hour),
        "1Day":  _TimeFrame(1,  _TimeFrameUnit.Day),
    }
    tf = _tf_map.get(timeframe, _TimeFrame(1, _TimeFrameUnit.Hour))

    end = datetime.now(timezone.utc)
    # IMPORTANT: passing both `start` and `limit` to Alpaca returns the OLDEST
    # `limit` bars in the window, not the newest. We therefore omit `limit` and
    # size the lookback window per timeframe, then keep the most recent `limit`
    # bars via df.tail() after sorting.
    _lookback_days = {
        "1Min": 7, "5Min": 21, "15Min": 45, "1Hour": 120, "1Day": 800,
    }.get(timeframe, 7)
    start = end - timedelta(days=_lookback_days)

    req = _StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=start,
        end=end,
        feed=_DataFeed.IEX,
    )

    try:
        bars = _get_data_client().get_stock_bars(req)
        df = bars.df
    except Exception as exc:
        # Reset client and retry once
        log.debug("Bar fetch attempt 1 failed for %s (%s) — retrying", symbol, exc)
        _data_client = None
        time.sleep(0.5)
        bars = _get_data_client().get_stock_bars(req)
        df = bars.df

    if df is None:
        raise ValueError(f"No data returned for {symbol} from IEX feed")

    if df.empty:
        raise ValueError(f"Empty DataFrame returned for {symbol}")

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level=0)

    df = df.rename(columns=str.lower)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()

    # Keep only the most recent `limit` bars. The window above deliberately
    # fetches more than needed to guarantee we have up-to-date data.
    if limit and len(df) > limit:
        df = df.tail(limit)

    return df


def _build_bar_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    last = df.iloc[-1]
    first_today = df[df.index.date == df.index[-1].date()].iloc[0] if len(df) > 0 else last
    avg_vol = df["volume"].tail(20).mean()
    return {
        "current_price": float(last["close"]),
        "daily_open": float(first_today["open"]),
        "daily_high": float(df[df.index.date == df.index[-1].date()]["high"].max()),
        "daily_low": float(df[df.index.date == df.index[-1].date()]["low"].min()),
        "daily_change_pct": (float(last["close"]) - float(first_today["open"])) / float(first_today["open"]) * 100,
        "avg_volume": float(avg_vol),
        "volume_ratio": float(last["volume"]) / float(avg_vol) if avg_vol > 0 else 1.0,
    }


def _get_portfolio_context(trading_client) -> dict:
    try:
        account = trading_client.get_account()
        positions = trading_client.get_all_positions()
        return {
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "open_positions": len(positions),
        }
    except Exception as exc:
        log.error("Could not fetch portfolio context: %s", exc)
        return {"buying_power": 0.0, "portfolio_value": 0.0, "open_positions": 0}


def _is_market_open() -> bool:
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    market_open  = now.replace(hour=config.MARKET_OPEN_HOUR,  minute=config.MARKET_OPEN_MINUTE,  second=0, microsecond=0)
    market_close = now.replace(hour=config.MARKET_CLOSE_HOUR, minute=config.MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    return market_open <= now <= market_close


# ─── Single symbol scan ───────────────────────────────────────────────────────

def scan_symbol(
    symbol: str,
    trading_client,
    portfolio_context: dict,
    confirm_test: bool = False,
) -> dict:
    """
    Full analysis pipeline for one symbol. Returns a report dict.
    """
    log.info("Scanning %s", symbol)

    try:
        df = _get_bars(trading_client, symbol, timeframe=config.BAR_TIMEFRAME, limit=config.BAR_LIMIT)
        log.info("TRACE bars OK %s rows=%d", symbol, len(df))
    except Exception as exc:
        log.error("TRACE bars FAILED %s: %s", symbol, exc, exc_info=True)
        return {"symbol": symbol, "error": str(exc)}

    if df.empty or len(df) < 25:
        log.warning("TRACE bars INSUFFICIENT %s (%d bars)", symbol, len(df))
        return {"symbol": symbol, "error": "insufficient bar data"}

    # Run all four strategies
    macd_sig = get_macd_signal(df)
    vwap_sig = get_vwap_signal(df)
    ema_sig = get_ema_signal(df)
    pa_sig = get_price_action_signal(df)

    # Confirmation engine
    confirmation_report = evaluate_confirmation(
        macd_signal=macd_sig,
        vwap_signal=vwap_sig,
        ema_signal=ema_sig,
        price_action_signal=pa_sig,
        min_required=config.MIN_SIGNALS_REQUIRED,
        min_strength=config.MIN_SIGNAL_STRENGTH,
        mode=config.CONFIRMATION_MODE,
        allow_shorts=config.ALLOW_SHORTS,
    )

    bar_summary = _build_bar_summary(df)

    result = {
        "symbol": symbol,
        "confirmation_report": confirmation_report,
        "bar_summary": bar_summary,
        "signals": {
            "macd": macd_sig,
            "vwap": vwap_sig,
            "ema_cross": ema_sig,
            "price_action": pa_sig,
        },
    }

    if confirm_test:
        return result

    portfolio_context["current_position"] = _get_current_position(trading_client, symbol)

    if config.USE_AI:
        # Ask Claude for a decision
        try:
            decision = get_trade_decision(
                symbol=symbol,
                bar_summary=bar_summary,
                confirmation_report=confirmation_report,
                portfolio_context=portfolio_context,
            )
        except Exception as exc:
            log.error("Claude error for %s: %s", symbol, exc)
            return {**result, "error": f"Claude error: {exc}"}
    else:
        # Build decision directly from confirmation engine — no AI involved
        direction = confirmation_report.get("direction", "no_trade")
        confirmed = confirmation_report.get("confirmed", False)
        grade = confirmation_report.get("quality", "F")
        size_modifier = {"A": 1.0, "B": 0.9, "C": 0.75}.get(grade, 0.0)
        _grade_rank = {"A": 3, "B": 2, "C": 1}
        grade_ok = _grade_rank.get(grade, 0) >= _grade_rank.get(config.MIN_GRADE, 1)
        action = direction if confirmed and direction in ("buy", "sell") and grade_ok else "hold"
        decision = {
            "action": action,
            "confidence": confirmation_report.get("avg_confirming_strength", 0.0),
            "reasoning": f"USE_AI=false — acting on confirmation engine alone. {confirmation_report.get('summary', '')}",
            "stop_loss_pct": config.STOP_LOSS_PCT,
            "take_profit_pct": config.TAKE_PROFIT_PCT,
            "position_size_modifier": size_modifier,
            "confirmation_quality": grade,
            "signal_count": confirmation_report.get("signal_count", "0/4"),
            "overriding_confirmation": False,
            "override_reason": None,
            "symbol": symbol,
        }
        log.info(
            "AI disabled — confirmation-only decision for %s: action=%s grade=%s",
            symbol, action, grade,
        )

    result["decision"] = decision

    # Trend pre-filter: override action to hold if it opposes the macro session trend
    if config.TREND_FILTER_ENABLED and decision.get("action") in ("buy", "sell"):
        _trend = get_trend_direction(df, config.TREND_FILTER_PERIOD)
        _action = decision["action"]
        if (_action == "buy" and _trend == "bear") or (_action == "sell" and _trend == "bull"):
            log.info(
                "TREND FILTER: blocked %s %s — session trend is %s (price %s EMA%d)",
                _action.upper(), symbol, _trend,
                "below" if _trend == "bear" else "above",
                config.TREND_FILTER_PERIOD,
            )
            decision["action"] = "hold"
            decision["override_reason"] = f"trend_filter: session trend is {_trend}"

    # Risk gate
    positions = trading_client.get_all_positions()
    existing_pos = next(
        (float(p.qty) for p in positions if p.symbol == symbol), None
    )
    # Daily P&L from Alpaca account equity (equity - last_equity = today's change).
    # This is reliable even when bracket stop/target orders are filled by Alpaca
    # mid-session without the local DB being updated.
    try:
        _acct = trading_client.get_account()
        daily_pnl = float(_acct.equity) - float(_acct.last_equity)
    except Exception:
        daily_pnl = db.get_daily_pnl()  # fall back to local DB if API call fails
    current_price = bar_summary.get("current_price", 1.0)
    portfolio_value = portfolio_context.get("portfolio_value", 0.0)
    trade_value = calculate_shares(
        portfolio_value, current_price, decision.get("position_size_modifier", 1.0)
    ) * current_price

    risk_result = run_risk_gate(
        symbol=symbol,
        direction=decision.get("action", "hold"),
        confirmation_report=confirmation_report,
        trade_value=trade_value,
        portfolio_value=portfolio_value,
        open_position_count=len(positions),
        existing_position=existing_pos,
        daily_pnl=daily_pnl,
        trading_client=trading_client,
        pyramid_count=_symbol_entries_today.get(symbol, 0),
    )

    result["risk_result"] = risk_result

    # Log decision to DB
    log.info(
        "TRACE log_decision %s action=%s grade=%s risk_approved=%s",
        symbol,
        decision.get("action"),
        decision.get("confirmation_quality"),
        risk_result.get("approved"),
    )
    decision_id = db.log_decision(
        symbol=symbol,
        decision=decision,
        confirmation_report=confirmation_report,
        risk_result=risk_result,
    )
    log.info("TRACE log_decision OK %s id=%s", symbol, decision_id)

    # Execute if approved
    if risk_result["approved"] and decision.get("action") != "hold":
        log.info("Executing %s %s", decision["action"], symbol)
        execution = execute_trade(
            symbol=symbol,
            decision=decision,
            portfolio_value=portfolio_value,
            current_price=current_price,
            trading_client=trading_client,
            existing_position=existing_pos,
        )
        result["execution"] = execution
        if execution and execution.get("fill_price"):
            _symbol_entries_today[symbol] = _symbol_entries_today.get(symbol, 0) + 1
            direction_label = "long" if decision["action"] == "buy" else "short"
            shares_executed = calculate_shares(
                portfolio_value, current_price, decision.get("position_size_modifier", 1.0)
            )
            db.log_trade(
                symbol=symbol,
                direction=direction_label,
                shares=shares_executed,
                fill_price=execution["fill_price"],
                stop_price=execution.get("stop"),
                target_price=execution.get("target"),
                decision_id=decision_id,
            )
    else:
        reason = risk_result.get("blocking_reason") or "action=hold"
        log.info("Trade blocked for %s: %s", symbol, reason)

    return result


def _get_current_position(trading_client, symbol: str) -> str:
    try:
        pos = trading_client.get_open_position(symbol)
        qty = float(pos.qty)
        side = "long" if qty > 0 else "short"
        return f"{side} {abs(qty)} shares"
    except Exception:
        return "none"


# ─── Confirm-test mode ────────────────────────────────────────────────────────

def run_confirm_test(symbols: list[str], trading_client) -> None:
    """
    Print a full confirmation report for each symbol without calling Claude
    or executing any orders. Great for tuning MIN_SIGNALS_REQUIRED.
    """
    from rich.console import Console
    from rich.rule import Rule
    from rich import print as rprint

    console = Console()
    console.print(Rule("[bold cyan]CONFIRMATION TEST MODE[/bold cyan]"))
    console.print(f"  MIN_SIGNALS_REQUIRED : [cyan]{config.MIN_SIGNALS_REQUIRED}[/cyan]")
    console.print(f"  MIN_SIGNAL_STRENGTH  : [cyan]{config.MIN_SIGNAL_STRENGTH}[/cyan]")
    console.print(f"  CONFIRMATION_MODE    : [cyan]{config.CONFIRMATION_MODE}[/cyan]")
    console.print(f"  ALLOW_SHORTS         : [cyan]{config.ALLOW_SHORTS}[/cyan]")
    console.print()

    symbol_reports = []
    for symbol in symbols:
        result = scan_symbol(symbol, trading_client, {}, confirm_test=True)
        symbol_reports.append(result)

        report = result.get("confirmation_report", {})
        confirmed = report.get("confirmed", False)
        grade = report.get("quality", "F")
        direction = report.get("direction", "no_trade")
        summary = report.get("summary", "")
        votes = report.get("votes", [])

        colour = "green" if confirmed else "red"
        console.print(f"[bold white]{symbol}[/bold white]  [{colour}]{summary}[/{colour}]")

        for v in votes:
            strat = v["strategy"].ljust(14)
            vote_colour = (
                "green" if v["vote"] in ("buy", "sell") and confirmed
                else ("red" if v["vote"] in ("buy", "sell") else "dim white")
            )
            console.print(
                f"  {strat}  [{vote_colour}]{v['vote'].upper():7s}[/{vote_colour}]  "
                f"strength={v['strength']:.3f}  {v['reason']}"
            )

        if confirmed:
            console.print(
                f"  → Would trigger: [bold green]{direction.upper()}[/bold green]  "
                f"Grade [bold]{grade}[/bold]"
            )
        else:
            console.print(f"  → [dim]No trade would be triggered[/dim]")
        console.print()

    render_snapshot(symbol_reports, status="Confirm-test complete")


# ─── End-of-day position close ────────────────────────────────────────────────

_eod_closed_today: bool = False  # ensure we only liquidate once per trading day
_symbol_entries_today: dict[str, int] = {}  # pyramid entry counter, reset each day

_EOD_VERIFY_ATTEMPTS: int = 4    # re-check attempts after close_all_positions
_EOD_VERIFY_WAIT_S: float = 3.0  # seconds between each verification poll


def _is_eod_close_window() -> bool:
    """Return True if we are within config.EOD_CLOSE_MINUTES_BEFORE of market close."""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    market_close = now.replace(
        hour=config.MARKET_CLOSE_HOUR,
        minute=config.MARKET_CLOSE_MINUTE,
        second=0,
        microsecond=0,
    )
    cutoff = market_close - timedelta(minutes=config.EOD_CLOSE_MINUTES_BEFORE)
    # Allow up to 2 minutes past official close to handle late fills
    return cutoff <= now <= market_close + timedelta(minutes=2)


def close_all_positions_eod(trading_client, dashboard: Optional[LiveDashboard]) -> None:
    """
    End-of-day liquidation routine.

    Execution order:
      1. Cancel every open order (including GTC stop/limit brackets).
         GTC orders survive overnight — if not cancelled they can trigger the
         next morning at stale prices.
      2. Close every open position via close_all_positions(cancel_orders=True),
         which submits market orders for all positions atomically.
      3. Verify all positions are gone; retry any stragglers up to
         _EOD_VERIFY_ATTEMPTS times.

    This does NOT guarantee profit — it prevents *overnight* exposure only.
    """
    global _eod_closed_today
    if _eod_closed_today:
        return

    log.info(
        "EOD: starting liquidation — %d min before close",
        config.EOD_CLOSE_MINUTES_BEFORE,
    )
    if dashboard:
        dashboard.update(
            [],
            status=f"EOD: liquidating all positions ({config.EOD_CLOSE_MINUTES_BEFORE} min before close)",
            last_scan=datetime.now(),
        )

    # ── Step 1: cancel all open orders (GTC brackets, pending entries, etc.) ──
    try:
        cancelled = trading_client.cancel_orders()
        count = len(cancelled) if cancelled else 0
        if count:
            log.info("EOD: cancelled %d open order(s)", count)
        else:
            log.info("EOD: no open orders to cancel")
    except Exception as exc:
        log.error("EOD: failed to cancel open orders: %s", exc)

    # Brief pause so cancellations propagate on Alpaca's side
    time.sleep(1)

    # ── Step 2: check whether there are any positions to close ────────────────
    try:
        positions = trading_client.get_all_positions()
    except Exception as exc:
        log.error("EOD: failed to fetch positions: %s", exc)
        _eod_closed_today = True
        return

    if not positions:
        log.info("EOD: no open positions — nothing to close")
        _eod_closed_today = True
        return

    log.info("EOD: %d open position(s) to liquidate", len(positions))

    # Capture current prices before submitting close orders — used to update
    # the local DB trade records once fills are confirmed.
    close_prices: dict[str, float] = {
        pos.symbol: float(pos.current_price)
        for pos in positions
        if pos.current_price is not None
    }

    # ── Step 3: close all positions atomically ────────────────────────────────
    try:
        trading_client.close_all_positions(cancel_orders=True)
        log.info("EOD: close_all_positions submitted")
    except Exception as exc:
        log.error(
            "EOD: close_all_positions failed (%s) — falling back to per-symbol close",
            exc,
        )
        for pos in positions:
            try:
                trading_client.close_position(pos.symbol)
                log.info("EOD: closed %s (fallback)", pos.symbol)
            except Exception as e:
                log.error("EOD: fallback close failed for %s: %s", pos.symbol, e)

    # ── Step 4: verify + retry any stragglers ─────────────────────────────────
    for attempt in range(1, _EOD_VERIFY_ATTEMPTS + 1):
        time.sleep(_EOD_VERIFY_WAIT_S)
        try:
            remaining = trading_client.get_all_positions()
        except Exception as exc:
            log.error("EOD: verification poll %d failed: %s", attempt, exc)
            break

        if not remaining:
            log.info("EOD: all positions confirmed closed (check %d)", attempt)
            break

        log.warning(
            "EOD: %d position(s) still open on check %d — retrying close",
            len(remaining),
            attempt,
        )
        for pos in remaining:
            try:
                trading_client.close_position(pos.symbol)
            except Exception as e:
                log.error("EOD: retry close failed for %s: %s", pos.symbol, e)
    else:
        log.error(
            "EOD: %d position(s) may still be open after all retry attempts — "
            "check Alpaca dashboard immediately",
            len(remaining),  # type: ignore[possibly-undefined]
        )

    # ── Step 5: mark all open trades as closed in the local database ──────────
    # Query open DB records for each symbol that was closed on Alpaca, then
    # record the close price and compute realised P&L.
    try:
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(config.DB_PATH)
        conn.row_factory = _sqlite3.Row
        open_trades = conn.execute(
            "SELECT id, symbol FROM trades WHERE closed = 0"
        ).fetchall()
        conn.close()

        for row in open_trades:
            symbol = row["symbol"]
            price = close_prices.get(symbol)
            if price is None:
                log.warning(
                    "EOD: no close price available for DB trade id=%d (%s) — "
                    "record left open; run generate_trade_review.py to reconcile",
                    row["id"], symbol,
                )
                continue
            try:
                db.close_trade(row["id"], price)
                log.info(
                    "EOD: DB trade id=%d (%s) marked closed @ %.4f",
                    row["id"], symbol, price,
                )
            except Exception as exc:
                log.error(
                    "EOD: failed to mark trade id=%d closed in DB: %s",
                    row["id"], exc,
                )
    except Exception as exc:
        log.error("EOD: DB close-trade update failed: %s", exc)

    _eod_closed_today = True


# ─── Trade timeout check (live bot) ──────────────────────────────────────────

_BAR_TIMEFRAME_MINUTES = {
    "1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60, "1Day": 1440,
}


def _check_position_timeouts(trading_client) -> int:
    """
    Close any open positions that have been held for >= TRADE_TIMEOUT_BARS bars
    without moving TRADE_TIMEOUT_MIN_PROGRESS_PCT toward their target.

    Returns the number of positions closed by timeout.
    """
    if config.TRADE_TIMEOUT_BARS <= 0:
        return 0

    bar_minutes = _BAR_TIMEFRAME_MINUTES.get(config.BAR_TIMEFRAME, 1)
    timeout_minutes = config.TRADE_TIMEOUT_BARS * bar_minutes
    now_utc = datetime.now(timezone.utc)

    open_db_trades = db.get_open_trades()
    if not open_db_trades:
        return 0

    closed_count = 0
    for trade in open_db_trades:
        symbol = trade["symbol"]
        fill_price = trade["fill_price"]
        target_price = trade["target_price"]
        direction = trade["direction"]
        trade_id = trade["id"]

        if not fill_price or not target_price:
            continue

        try:
            entry_dt = datetime.fromisoformat(trade["ts"]).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        minutes_held = (now_utc - entry_dt).total_seconds() / 60
        if minutes_held < timeout_minutes:
            continue

        try:
            pos = trading_client.get_open_position(symbol)
            current_price = float(pos.current_price)
        except Exception:
            continue

        if direction == "long":
            progress = (current_price - fill_price) / fill_price
        else:
            progress = (fill_price - current_price) / fill_price

        if progress >= config.TRADE_TIMEOUT_MIN_PROGRESS_PCT:
            continue

        log.info(
            "TIMEOUT: closing %s %s — held %.0f min (>= %d bars), "
            "progress %.2f%% < %.0f%% threshold",
            direction.upper(), symbol,
            minutes_held, config.TRADE_TIMEOUT_BARS,
            progress * 100, config.TRADE_TIMEOUT_MIN_PROGRESS_PCT * 100,
        )
        try:
            trading_client.close_position(symbol)
            db.close_trade(trade_id, current_price)
            closed_count += 1
        except Exception as exc:
            log.error("TIMEOUT: failed to close %s: %s", symbol, exc)

    return closed_count


# ─── Main loop ────────────────────────────────────────────────────────────────

def run_once(symbols: list[str], trading_client, dashboard: Optional[LiveDashboard]) -> int:
    """Run one full scan cycle. Returns number of trades taken."""
    if not _is_market_open():
        log.info("Market is closed — skipping scan")
        if dashboard:
            dashboard.update([], status="Market closed (waiting for 09:30 ET)", last_scan=datetime.now())
        return 0

    _check_position_timeouts(trading_client)

    portfolio_context = _get_portfolio_context(trading_client)
    symbol_reports = []
    trades_taken = 0
    errors = []

    for symbol in symbols:
        try:
            result = scan_symbol(symbol, trading_client, portfolio_context)
            symbol_reports.append(result)
            if result.get("execution") and result["execution"].get("fill_price"):
                trades_taken += 1
        except Exception as exc:
            log.exception("Unhandled error scanning %s", symbol)
            errors.append(f"{symbol}: {exc}")

    stats = db.get_confirmation_stats()
    if dashboard:
        dashboard.update(
            symbol_reports,
            stats=stats,
            status=f"Last scan: {trades_taken} trade(s) taken",
            last_scan=datetime.now(),
        )

    db.log_scan_run(symbols, trades_taken, errors)
    return trades_taken


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Trading Bot")
    parser.add_argument(
        "--confirm-test",
        action="store_true",
        help="Print confirmation reports for all watchlist symbols and exit.",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Comma-separated symbol(s). Defaults to WATCHLIST in .env.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan cycle and exit.",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run backtester against historical data and exit.",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Backtest start date (default: 180 days ago).",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Backtest end date (default: yesterday).",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10_000.0,
        help="Starting capital for backtest (default: 10000).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default=None,
        choices=["strict", "weighted"],
        help="Override CONFIRMATION_MODE for backtest.",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default=None,
        choices=["1Min", "5Min", "15Min", "1Hour", "1Day"],
        help="Override BAR_TIMEFRAME for backtest (default: uses .env value).",
    )
    parser.add_argument(
        "--live-backtest",
        action="store_true",
        help="Run live-style multi-symbol backtest (shared capital, max 6 positions).",
    )
    parser.add_argument(
        "--min-grade",
        type=str,
        default=config.MIN_GRADE,
        choices=["A", "B", "C"],
        help="Minimum confirmation grade to trade in live-backtest (default: from .env MIN_GRADE).",
    )
    parser.add_argument(
        "--timeout-bars",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Close positions open >= N bars without making sufficient progress toward target. "
            "0 = disabled (default: TRADE_TIMEOUT_BARS from .env)."
        ),
    )
    parser.add_argument(
        "--timeout-progress",
        type=float,
        default=None,
        metavar="PCT",
        help=(
            "Minimum fractional progress toward target to avoid timeout "
            "(e.g. 0.02 = 2%%). Default: TRADE_TIMEOUT_MIN_PROGRESS_PCT from .env."
        ),
    )
    parser.add_argument(
        "--timeout-relative",
        action="store_true",
        default=False,
        help=(
            "Interpret --timeout-progress as a fraction of the full target distance "
            "rather than an absolute price move (e.g. 0.15 = must be 15%% of the way "
            "to target; for a 6%% target that means 0.9%%)."
        ),
    )
    args = parser.parse_args()

    # Support comma-separated symbols: --symbol AAPL,MSFT,GLD
    if args.symbol:
        symbols = [s.strip().upper() for s in args.symbol.split(",") if s.strip()]
    else:
        symbols = config.WATCHLIST

    # ── Live-style backtest mode ──────────────────────────────────────────────
    if args.live_backtest:
        from live_backtest import run_live_backtest, print_live_backtest_report
        result = run_live_backtest(
            symbols=symbols,
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
            mode=args.mode,
            timeframe=args.timeframe or config.BAR_TIMEFRAME,
            min_grade=args.min_grade,
            timeout_bars=args.timeout_bars,
            timeout_min_progress_pct=args.timeout_progress,
            timeout_relative=args.timeout_relative,
        )
        print_live_backtest_report(result)
        sys.exit(0)

    # ── Backtest mode ─────────────────────────────────────────────────────────
    if args.backtest:
        from backtester import run_backtest_multi
        run_backtest_multi(
            symbols=symbols,
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
            mode=args.mode,
            timeframe=args.timeframe or config.BAR_TIMEFRAME,
        )
        sys.exit(0)

    # ── Live / paper trading ──────────────────────────────────────────────────
    db.init_db()
    trading_client = get_trading_client()

    if args.confirm_test:
        run_confirm_test(symbols, trading_client)
        sys.exit(0)

    log.info("Trading bot starting — watchlist: %s", symbols)

    if args.once:
        run_once(symbols, trading_client, dashboard=None)
        sys.exit(0)

    with LiveDashboard() as dash:
        current_day: Optional[int] = None
        while True:
            try:
                global _eod_closed_today
                # Reset the EOD flag at the start of each new calendar day
                today = datetime.now().date().day
                if current_day is not None and today != current_day:
                    _eod_closed_today = False
                    _symbol_entries_today.clear()
                current_day = today

                # Close all positions if we are in the EOD window
                if _is_eod_close_window():
                    close_all_positions_eod(trading_client, dash)
                else:
                    run_once(symbols, trading_client, dashboard=dash)

            except KeyboardInterrupt:
                log.info("Shutting down.")
                break
            except Exception as exc:
                log.exception("Unhandled error in main loop: %s", exc)

            time.sleep(config.SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
