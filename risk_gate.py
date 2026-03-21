"""
Risk gate — ordered sequence of checks that must all pass before a trade executes.

Order (first failure blocks the trade immediately):
  1. Signal confirmation gate  (are enough strategies in agreement?)
  2. Short selling guard        (allowed in config? enabled on account?)
  3. Symbol shortability check  (can this specific ticker be shorted?)
  4. Position limits            (already at max open positions?)
  5. Position size              (trade size within allowed max?)
  6. Daily loss limit           (already down too much today?)
"""

from __future__ import annotations

import logging
from typing import Optional

import config

logger = logging.getLogger(__name__)


# ─── Individual gate functions ────────────────────────────────────────────────

def check_confirmation(confirmation_report: dict) -> tuple[bool, str]:
    """
    Hard gate: block immediately if signals are not confirmed.
    """
    if not confirmation_report["confirmed"]:
        return False, (
            f"Signal not confirmed: only {confirmation_report['buy_count']} buy / "
            f"{confirmation_report['sell_count']} sell strategies agree "
            f"(need {confirmation_report['min_required']}). "
            f"Abstaining: {confirmation_report['abstaining_strategies']}. "
            f"Summary: {confirmation_report['summary']}"
        )

    if confirmation_report["quality"] == "C":
        logger.warning(
            "Grade C setup for direction=%s — proceeding with caution. %s",
            confirmation_report["direction"],
            confirmation_report["summary"],
        )

    return True, (
        f"Confirmed {confirmation_report['signal_count']} — "
        f"Grade {confirmation_report['quality']}"
    )


def check_shorts_allowed(direction: str, trading_client=None) -> tuple[bool, str]:
    """
    Two-layer short selling guard:
      1. Config-level: ALLOW_SHORTS must be true.
      2. Account-level: Alpaca account must have shorting enabled.
    """
    if direction != "sell":
        return True, "long trade — no short check needed"

    if not config.ALLOW_SHORTS:
        return False, "short selling disabled in config (ALLOW_SHORTS=false)"

    if trading_client is not None:
        try:
            account = trading_client.get_account()
            if not account.shorting_enabled:
                return False, (
                    "Alpaca account does not have shorting enabled. "
                    "Enable shorting in your Alpaca account settings "
                    "(Account → Settings → Shorting)."
                )
        except Exception as exc:
            logger.error("Could not verify account shorting status: %s", exc)
            return False, f"Could not verify account shorting status: {exc}"

    return True, "short selling allowed"


def check_symbol_shortable(symbol: str, trading_client=None) -> tuple[bool, str]:
    """
    Verify the specific symbol can be borrowed and shorted via Alpaca.
    """
    if trading_client is None:
        return True, "shortability check skipped (no client)"

    try:
        asset = trading_client.get_asset(symbol)
        if not (asset.shortable and asset.easy_to_borrow):
            return False, (
                f"{symbol} is not shortable or not easy-to-borrow on Alpaca. "
                f"(shortable={asset.shortable}, easy_to_borrow={asset.easy_to_borrow})"
            )
    except Exception as exc:
        logger.error("Could not check shortability for %s: %s", symbol, exc)
        return False, f"Could not verify shortability for {symbol}: {exc}"

    return True, f"{symbol} is shortable and easy-to-borrow"


def check_position_limits(
    open_position_count: int,
    existing_position: Optional[float] = None,
) -> tuple[bool, str]:
    """
    Block if already at max open positions. Adding to an existing position
    (pyramiding) is allowed provided MAX_OPEN_POSITIONS has not been reached.
    """
    if existing_position is not None and existing_position != 0:
        return True, f"adding to existing position ({existing_position} shares)"

    if open_position_count >= config.MAX_OPEN_POSITIONS:
        return False, (
            f"Max open positions reached: {open_position_count}/{config.MAX_OPEN_POSITIONS}"
        )

    return True, f"position count OK ({open_position_count}/{config.MAX_OPEN_POSITIONS})"


def check_position_size(
    trade_value: float,
    portfolio_value: float,
) -> tuple[bool, str]:
    """
    Block if the trade value would exceed MAX_POSITION_SIZE of portfolio.
    """
    if portfolio_value <= 0:
        return False, "portfolio value is zero or negative"

    fraction = trade_value / portfolio_value
    if fraction > config.MAX_POSITION_SIZE:
        return False, (
            f"Trade value ${trade_value:,.2f} is {fraction*100:.1f}% of portfolio "
            f"(max allowed: {config.MAX_POSITION_SIZE*100:.0f}%)"
        )

    return True, f"position size OK ({fraction*100:.1f}% of portfolio)"


def check_daily_loss_limit(
    daily_pnl: float,
    portfolio_value: float,
    max_daily_loss_pct: float = 0.03,
) -> tuple[bool, str]:
    """
    Block all new trades if today's realized losses exceed the daily limit.
    """
    if portfolio_value <= 0:
        return True, "daily loss check skipped (no portfolio value)"

    loss_pct = daily_pnl / portfolio_value
    if loss_pct < -max_daily_loss_pct:
        return False, (
            f"Daily loss limit reached: {loss_pct*100:.2f}% "
            f"(limit: -{max_daily_loss_pct*100:.0f}%)"
        )

    return True, f"daily P&L OK ({loss_pct*100:+.2f}%)"


# ─── Main gate runner ─────────────────────────────────────────────────────────

def run_risk_gate(
    symbol: str,
    direction: str,
    confirmation_report: dict,
    trade_value: float,
    portfolio_value: float,
    open_position_count: int,
    existing_position: Optional[float] = None,
    daily_pnl: float = 0.0,
    trading_client=None,
) -> dict:
    """
    Runs all risk checks in order. Returns a result dict:
    {
        "approved": bool,
        "blocking_check": str | None,
        "blocking_reason": str | None,
        "checks": [{"name": str, "passed": bool, "reason": str}, ...]
    }
    """
    checks_run = []

    def _run(name: str, passed: bool, reason: str) -> bool:
        checks_run.append({"name": name, "passed": passed, "reason": reason})
        if passed:
            logger.debug("Risk gate [%s] PASS — %s", name, reason)
        else:
            logger.warning("Risk gate [%s] FAIL — %s", name, reason)
        return passed

    # 1. Confirmation gate
    ok, reason = check_confirmation(confirmation_report)
    if not _run("confirmation", ok, reason):
        return _blocked("confirmation", reason, checks_run)

    # 2. Shorts policy
    ok, reason = check_shorts_allowed(direction, trading_client=trading_client)
    if not _run("shorts_policy", ok, reason):
        return _blocked("shorts_policy", reason, checks_run)

    # 3. Symbol shortability (only relevant for short trades)
    if direction == "sell":
        ok, reason = check_symbol_shortable(symbol, trading_client=trading_client)
        if not _run("symbol_shortable", ok, reason):
            return _blocked("symbol_shortable", reason, checks_run)
    else:
        _run("symbol_shortable", True, "long trade — skipped")

    # 4. Position limits
    ok, reason = check_position_limits(open_position_count, existing_position)
    if not _run("position_limits", ok, reason):
        return _blocked("position_limits", reason, checks_run)

    # 5. Position size
    ok, reason = check_position_size(trade_value, portfolio_value)
    if not _run("position_size", ok, reason):
        return _blocked("position_size", reason, checks_run)

    # 6. Daily loss limit
    ok, reason = check_daily_loss_limit(daily_pnl, portfolio_value)
    if not _run("daily_loss_limit", ok, reason):
        return _blocked("daily_loss_limit", reason, checks_run)

    logger.info("All risk checks PASSED for %s (%s)", symbol, direction)
    return {
        "approved": True,
        "blocking_check": None,
        "blocking_reason": None,
        "checks": checks_run,
    }


def _blocked(check_name: str, reason: str, checks: list) -> dict:
    return {
        "approved": False,
        "blocking_check": check_name,
        "blocking_reason": reason,
        "checks": checks,
    }


# ─── Logging helper ───────────────────────────────────────────────────────────

def log_warning(message: str) -> None:
    logger.warning(message)
