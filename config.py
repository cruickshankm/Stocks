"""
Central configuration — loads from .env and validates all settings.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _get_env(key: str, default=None, cast=str, required: bool = False):
    val = os.getenv(key, default)
    if required and val is None:
        raise EnvironmentError(f"Required environment variable '{key}' is not set.")
    if val is None:
        return None
    try:
        if cast is bool:
            return str(val).lower() in ("true", "1", "yes")
        return cast(val)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Cannot cast env var '{key}' to {cast.__name__}: {exc}") from exc


# ─── Alpaca ───────────────────────────────────────────────────────────────────
ALPACA_API_KEY: str = _get_env("ALPACA_API_KEY", required=True)
ALPACA_SECRET_KEY: str = _get_env("ALPACA_SECRET_KEY", required=True)
ALPACA_BASE_URL: str = _get_env("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# ─── Claude ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = _get_env("ANTHROPIC_API_KEY", required=True)
CLAUDE_MODEL: str = _get_env("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
USE_AI: bool = _get_env("USE_AI", "true", cast=bool)

# ─── Trading universe ─────────────────────────────────────────────────────────
_watchlist_raw: str = _get_env("WATCHLIST", "AAPL,MSFT,NVDA,SPY")
WATCHLIST: list[str] = [s.strip().upper() for s in _watchlist_raw.split(",") if s.strip()]

# ─── Risk / position sizing ───────────────────────────────────────────────────
MAX_POSITION_SIZE: float = _get_env("MAX_POSITION_SIZE", 0.10, cast=float)
MAX_PORTFOLIO_RISK: float = _get_env("MAX_PORTFOLIO_RISK", 0.02, cast=float)
STOP_LOSS_PCT: float = _get_env("STOP_LOSS_PCT", 0.02, cast=float)
TAKE_PROFIT_PCT: float = _get_env("TAKE_PROFIT_PCT", 0.04, cast=float)
MAX_OPEN_POSITIONS: int = _get_env("MAX_OPEN_POSITIONS", 5, cast=int)

# ─── Signal confirmation ──────────────────────────────────────────────────────
_min_signals_raw: int = _get_env("MIN_SIGNALS_REQUIRED", 3, cast=int)
if not (1 <= _min_signals_raw <= 4):
    logger.warning(
        "MIN_SIGNALS_REQUIRED=%d is outside valid range 1–4. Defaulting to 3.",
        _min_signals_raw,
    )
    _min_signals_raw = 3
MIN_SIGNALS_REQUIRED: int = _min_signals_raw

MIN_SIGNAL_STRENGTH: float = _get_env("MIN_SIGNAL_STRENGTH", 0.55, cast=float)
ALLOW_SHORTS: bool = _get_env("ALLOW_SHORTS", "true", cast=bool)

_min_grade_raw: str = _get_env("MIN_GRADE", "C").upper()
if _min_grade_raw not in ("A", "B", "C"):
    logger.warning("MIN_GRADE='%s' is invalid. Defaulting to 'C'.", _min_grade_raw)
    _min_grade_raw = "C"
MIN_GRADE: str = _min_grade_raw

_mode_raw: str = _get_env("CONFIRMATION_MODE", "strict").lower()
if _mode_raw not in ("strict", "weighted"):
    logger.warning("CONFIRMATION_MODE='%s' is invalid. Defaulting to 'strict'.", _mode_raw)
    _mode_raw = "strict"
CONFIRMATION_MODE: str = _mode_raw

# ─── Strategy parameters ─────────────────────────────────────────────────────

# MACD
MACD_FAST: int   = _get_env("MACD_FAST",   12, cast=int)   # fast EMA period
MACD_SLOW: int   = _get_env("MACD_SLOW",   26, cast=int)   # slow EMA period
MACD_SIGNAL: int = _get_env("MACD_SIGNAL",  9, cast=int)   # signal line period

# VWAP
# Minimum % deviation from VWAP before a signal is considered (e.g. 0.5 = 0.5%)
VWAP_MIN_DEVIATION_PCT: float = _get_env("VWAP_MIN_DEVIATION_PCT", 0.5,  cast=float)
# Sensitivity: how quickly strength grows with deviation (lower = more sensitive)
VWAP_SENSITIVITY: float       = _get_env("VWAP_SENSITIVITY",       3.0,  cast=float)

# EMA cross
EMA_FAST: int = _get_env("EMA_FAST", 50,  cast=int)   # fast EMA (e.g. 50)
EMA_SLOW: int = _get_env("EMA_SLOW", 200, cast=int)   # slow EMA (e.g. 200)

# ─── Bar data ────────────────────────────────────────────────────────────────
# Timeframe used for live scanning. Options: 1Min, 5Min, 15Min, 1Hour, 1Day
# Note: EMA_SLOW requires this many bars of history — shorter timeframes generate
# signals faster but are noisier. 1Hour is the recommended default.
BAR_TIMEFRAME: str = _get_env("BAR_TIMEFRAME", "1Hour")
# How many bars to fetch per symbol on each scan
BAR_LIMIT: int = _get_env("BAR_LIMIT", 250, cast=int)

# ─── Scheduling ───────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS: int = _get_env("SCAN_INTERVAL_SECONDS", 60, cast=int)
MARKET_OPEN_HOUR: int = _get_env("MARKET_OPEN_HOUR", 9, cast=int)
MARKET_OPEN_MINUTE: int = _get_env("MARKET_OPEN_MINUTE", 30, cast=int)
MARKET_CLOSE_HOUR: int = _get_env("MARKET_CLOSE_HOUR", 16, cast=int)
MARKET_CLOSE_MINUTE: int = _get_env("MARKET_CLOSE_MINUTE", 0, cast=int)
# How many minutes before market close to cancel all orders and liquidate all
# positions. 10 minutes is recommended: gives enough time for market orders to
# fill before the exchange closes and avoids routing issues in the final minute.
EOD_CLOSE_MINUTES_BEFORE: int = _get_env("EOD_CLOSE_MINUTES_BEFORE", 10, cast=int)

# ─── Database ─────────────────────────────────────────────────────────────────
DB_PATH: str = _get_env("DB_PATH", "trading_log.db")

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = _get_env("LOG_LEVEL", "INFO").upper()
