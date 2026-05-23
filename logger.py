"""
SQLite-backed trade and decision logger.

Tables:
  decisions  — every time the bot evaluates a symbol
  trades     — every executed order (with fill details)
  scan_runs  — metadata for each main-loop scan

Provides get_confirmation_stats() for performance breakdown by grade.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Generator, Optional

import config

logger = logging.getLogger(__name__)


# ─── Schema ───────────────────────────────────────────────────────────────────

_CREATE_DECISIONS = """
CREATE TABLE IF NOT EXISTS decisions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                      TEXT    NOT NULL,
    symbol                  TEXT    NOT NULL,
    action                  TEXT,
    confidence              REAL,
    reasoning               TEXT,
    stop_loss_pct           REAL,
    take_profit_pct         REAL,
    position_size_modifier  REAL,

    -- Confirmation fields
    confirmed               INTEGER,
    quality_grade           TEXT,
    signal_count            TEXT,
    confirming_strategies   TEXT,
    conflicting_strategies  TEXT,
    abstaining_strategies   TEXT,
    direction_from_signals  TEXT,
    claude_overrode_signals INTEGER,
    override_reason         TEXT,
    votes_json              TEXT,

    -- Risk gate
    risk_approved           INTEGER,
    risk_blocking_check     TEXT,
    risk_blocking_reason    TEXT,

    -- Misc
    mode                    TEXT,
    buy_count               INTEGER,
    sell_count              INTEGER,
    abstain_count           INTEGER,
    weighted_buy_score      REAL,
    weighted_sell_score     REAL,
    avg_confirming_strength REAL
);
"""

_CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    direction       TEXT    NOT NULL,
    shares          INTEGER,
    fill_price      REAL,
    stop_price      REAL,
    target_price    REAL,
    decision_id     INTEGER REFERENCES decisions(id),
    closed          INTEGER DEFAULT 0,
    close_ts        TEXT,
    close_price     REAL,
    pnl             REAL,
    pnl_pct         REAL
);
"""

_CREATE_SCAN_RUNS = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    symbols     TEXT,
    trades_taken INTEGER DEFAULT 0,
    errors      TEXT
);
"""


# ─── Connection helper ────────────────────────────────────────────────────────

@contextmanager
def _db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with _db() as conn:
        conn.execute(_CREATE_DECISIONS)
        conn.execute(_CREATE_TRADES)
        conn.execute(_CREATE_SCAN_RUNS)
    logger.info("Database initialised at %s", config.DB_PATH)


# ─── Logging functions ────────────────────────────────────────────────────────

def log_decision(
    symbol: str,
    decision: dict,
    confirmation_report: dict,
    risk_result: dict,
) -> int:
    """
    Insert a full decision record. Returns the new row id.
    """
    ts = datetime.utcnow().isoformat()

    row = {
        "ts": ts,
        "symbol": symbol,
        "action": decision.get("action"),
        "confidence": decision.get("confidence"),
        "reasoning": decision.get("reasoning"),
        "stop_loss_pct": decision.get("stop_loss_pct"),
        "take_profit_pct": decision.get("take_profit_pct"),
        "position_size_modifier": decision.get("position_size_modifier"),
        # Confirmation
        "confirmed": int(bool(confirmation_report.get("confirmed"))),
        "quality_grade": confirmation_report.get("quality"),
        "signal_count": confirmation_report.get("signal_count"),
        "confirming_strategies": json.dumps(confirmation_report.get("confirming_strategies", [])),
        "conflicting_strategies": json.dumps(confirmation_report.get("conflicting_strategies", [])),
        "abstaining_strategies": json.dumps(confirmation_report.get("abstaining_strategies", [])),
        "direction_from_signals": confirmation_report.get("direction"),
        "claude_overrode_signals": int(bool(decision.get("overriding_confirmation"))),
        "override_reason": decision.get("override_reason"),
        "votes_json": json.dumps(confirmation_report.get("votes", [])),
        # Risk
        "risk_approved": int(bool(risk_result.get("approved"))),
        "risk_blocking_check": risk_result.get("blocking_check"),
        "risk_blocking_reason": risk_result.get("blocking_reason"),
        # Misc confirmation fields
        "mode": confirmation_report.get("mode"),
        "buy_count": confirmation_report.get("buy_count"),
        "sell_count": confirmation_report.get("sell_count"),
        "abstain_count": confirmation_report.get("abstain_count"),
        "weighted_buy_score": confirmation_report.get("weighted_buy_score"),
        "weighted_sell_score": confirmation_report.get("weighted_sell_score"),
        "avg_confirming_strength": confirmation_report.get("avg_confirming_strength"),
    }

    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    sql = f"INSERT INTO decisions ({cols}) VALUES ({placeholders})"

    with _db() as conn:
        cursor = conn.execute(sql, list(row.values()))
        return cursor.lastrowid


def log_trade(
    symbol: str,
    direction: str,
    shares: int,
    fill_price: float,
    stop_price: Optional[float],
    target_price: Optional[float],
    decision_id: Optional[int] = None,
) -> int:
    """Insert a trade execution record. Returns the new row id."""
    ts = datetime.utcnow().isoformat()

    sql = """
        INSERT INTO trades
            (ts, symbol, direction, shares, fill_price, stop_price, target_price, decision_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _db() as conn:
        cursor = conn.execute(
            sql,
            (ts, symbol, direction, shares, fill_price, stop_price, target_price, decision_id),
        )
        return cursor.lastrowid


def close_trade(trade_id: int, close_price: float) -> None:
    """Mark a trade as closed and compute P&L."""
    ts = datetime.utcnow().isoformat()
    with _db() as conn:
        row = conn.execute(
            "SELECT fill_price, shares, direction FROM trades WHERE id=?", (trade_id,)
        ).fetchone()
        if not row:
            logger.warning("Trade id=%d not found for closing", trade_id)
            return
        fill = row["fill_price"]
        shares = row["shares"]
        direction = row["direction"]
        if direction == "long":
            pnl = (close_price - fill) * shares
            pnl_pct = (close_price - fill) / fill
        else:
            pnl = (fill - close_price) * shares
            pnl_pct = (fill - close_price) / fill

        conn.execute(
            """
            UPDATE trades SET closed=1, close_ts=?, close_price=?, pnl=?, pnl_pct=?
            WHERE id=?
            """,
            (ts, close_price, pnl, pnl_pct, trade_id),
        )


def log_scan_run(symbols: list[str], trades_taken: int, errors: list[str]) -> None:
    ts = datetime.utcnow().isoformat()
    with _db() as conn:
        conn.execute(
            "INSERT INTO scan_runs (ts, symbols, trades_taken, errors) VALUES (?, ?, ?, ?)",
            (ts, json.dumps(symbols), trades_taken, json.dumps(errors)),
        )


# ─── Analysis ─────────────────────────────────────────────────────────────────

def get_confirmation_stats() -> dict:
    """
    Performance breakdown by confirmation quality grade.

    Returns:
    {
        "A_grade":          {"trades": int, "wins": int, "win_rate": float, "avg_pnl": float},
        "B_grade":          { ... },
        "C_grade":          { ... },
        "overrides":        {"trades": int, "wins": int, "win_rate": float},
        "total_trades":     int,
        "overall_win_rate": float,
    }
    """
    sql = """
        SELECT
            d.quality_grade,
            d.claude_overrode_signals,
            t.pnl
        FROM trades t
        JOIN decisions d ON t.decision_id = d.id
        WHERE t.closed = 1
    """
    with _db() as conn:
        rows = conn.execute(sql).fetchall()

    buckets: dict[str, dict[str, Any]] = {
        "A_grade": {"trades": 0, "wins": 0, "pnl_sum": 0.0},
        "B_grade": {"trades": 0, "wins": 0, "pnl_sum": 0.0},
        "C_grade": {"trades": 0, "wins": 0, "pnl_sum": 0.0},
        "overrides": {"trades": 0, "wins": 0, "pnl_sum": 0.0},
    }

    total_trades = 0
    total_wins = 0

    for row in rows:
        grade = row["quality_grade"] or "F"
        pnl = float(row["pnl"] or 0)
        overrode = bool(row["claude_overrode_signals"])
        win = pnl > 0
        total_trades += 1
        if win:
            total_wins += 1

        if overrode:
            b = buckets["overrides"]
        elif grade == "A":
            b = buckets["A_grade"]
        elif grade == "B":
            b = buckets["B_grade"]
        elif grade == "C":
            b = buckets["C_grade"]
        else:
            continue

        b["trades"] += 1
        b["pnl_sum"] += pnl
        if win:
            b["wins"] += 1

    result: dict[str, Any] = {}
    for key, data in buckets.items():
        t = data["trades"]
        w = data["wins"]
        result[key] = {
            "trades": t,
            "wins": w,
            "win_rate": round(w / t, 4) if t > 0 else 0.0,
            "avg_pnl": round(data["pnl_sum"] / t, 2) if t > 0 else 0.0,
        }

    result["total_trades"] = total_trades
    result["overall_win_rate"] = round(total_wins / total_trades, 4) if total_trades > 0 else 0.0

    return result


def get_open_trades() -> list[dict]:
    """Return all open (unclosed) trade records ordered by entry time."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE closed = 0 ORDER BY ts ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_decisions(symbol: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Return the most recent decision records, optionally filtered by symbol."""
    if symbol:
        sql = "SELECT * FROM decisions WHERE symbol=? ORDER BY id DESC LIMIT ?"
        params = (symbol, limit)
    else:
        sql = "SELECT * FROM decisions ORDER BY id DESC LIMIT ?"
        params = (limit,)

    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_daily_pnl(day: Optional[date] = None) -> float:
    """Return total realised P&L for a given day (defaults to today)."""
    target = (day or date.today()).isoformat()
    sql = "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE date(close_ts)=? AND closed=1"
    with _db() as conn:
        row = conn.execute(sql, (target,)).fetchone()
    return float(row["total"]) if row else 0.0
