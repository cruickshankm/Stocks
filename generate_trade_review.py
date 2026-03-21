"""
Generate TRADE_REVIEW.md — a full human-readable post-mortem of every trade
recorded in trading_log.db.

Usage:
    python generate_trade_review.py              # all trades
    python generate_trade_review.py --date 2026-03-17  # specific day (ET)
    python generate_trade_review.py --symbol QQQ       # specific symbol

The file is written to TRADE_REVIEW.md in the current directory and is
overwritten each time you run the script.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

DB_PATH = "trading_log.db"
OUT_PATH = "TRADE_REVIEW.md"

ET = timezone(timedelta(hours=-4))  # Eastern Time (EDT, Mar–Nov)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def utc_to_et(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
    return dt.astimezone(ET)


def fmt_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S ET")


def fmt_price(v) -> str:
    if v is None:
        return "—"
    return f"${float(v):,.4f}"


def fmt_money(v) -> str:
    if v is None:
        return "—"
    return f"${float(v):,.2f}"


def fmt_pct(v) -> str:
    if v is None:
        return "—"
    return f"{float(v) * 100:+.2f}%"


def hold_duration(open_dt: Optional[datetime], close_dt: Optional[datetime]) -> str:
    if open_dt is None:
        return "—"
    end = close_dt or datetime.now(timezone.utc).astimezone(ET)
    delta = end - open_dt
    total_s = int(delta.total_seconds())
    if total_s < 0:
        return "—"
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    label = " ".join(parts)
    if close_dt is None:
        label += " *(still open)*"
    return label


def pnl_emoji(pnl) -> str:
    if pnl is None:
        return "⏳"
    return "✅" if float(pnl) >= 0 else "❌"


def grade_label(grade) -> str:
    labels = {"A": "A — Excellent", "B": "B — Good", "C": "C — Marginal", "F": "F — Failed"}
    return labels.get(grade, grade or "—")


def parse_votes(votes_json) -> list[dict]:
    if not votes_json:
        return []
    try:
        return json.loads(votes_json)
    except Exception:
        return []


def vote_icon(vote: str) -> str:
    return {"buy": "▲ BUY", "sell": "▼ SELL", "abstain": "— ABSTAIN"}.get(vote, vote)


# ─── DB query ─────────────────────────────────────────────────────────────────

def load_trades(
    date_filter: Optional[str] = None,
    symbol_filter: Optional[str] = None,
) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    where_clauses = []
    params: list = []

    if date_filter:
        # ts is stored as UTC; convert supplied ET date to a UTC range
        day_et = datetime.strptime(date_filter, "%Y-%m-%d").replace(tzinfo=ET)
        utc_start = day_et.astimezone(timezone.utc).isoformat()
        utc_end = (day_et + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        where_clauses.append("t.ts >= ? AND t.ts < ?")
        params += [utc_start, utc_end]

    if symbol_filter:
        where_clauses.append("t.symbol = ?")
        params.append(symbol_filter.upper())

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = f"""
        SELECT
            t.id, t.ts, t.symbol, t.direction, t.shares,
            t.fill_price, t.stop_price, t.target_price,
            t.closed, t.close_ts, t.close_price, t.pnl, t.pnl_pct,
            d.confidence, d.reasoning, d.quality_grade,
            d.confirming_strategies, d.conflicting_strategies,
            d.abstaining_strategies, d.votes_json,
            d.weighted_buy_score, d.weighted_sell_score,
            d.avg_confirming_strength, d.claude_overrode_signals,
            d.override_reason, d.mode,
            d.buy_count, d.sell_count, d.abstain_count
        FROM trades t
        LEFT JOIN decisions d ON t.decision_id = d.id
        {where}
        ORDER BY t.ts ASC
    """
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


# ─── Markdown builder ─────────────────────────────────────────────────────────

def build_markdown(trades: list[dict]) -> str:
    lines: list[str] = []

    now_et = datetime.now(timezone.utc).astimezone(ET)
    lines += [
        "# Trade Review",
        "",
        f"> Generated: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}  ",
        f"> Source: `{DB_PATH}`  ",
        f"> Total trades in this report: **{len(trades)}**",
        "",
    ]

    if not trades:
        lines.append("_No trades found matching the filter criteria._")
        return "\n".join(lines)

    # ── Summary table ────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## Summary",
        "",
        "| # | Symbol | Dir | Entry (ET) | Shares | Trade Value | Entry Price | Exit Price | P&L | P&L % | Grade | Status |",
        "|---|--------|-----|-----------|--------|-------------|-------------|------------|-----|-------|-------|--------|",
    ]

    total_pnl = 0.0
    pnl_known = False

    for t in trades:
        open_dt = utc_to_et(t["ts"])
        trade_value = (t["shares"] or 0) * (t["fill_price"] or 0)
        pnl_cell = fmt_money(t["pnl"]) if t["pnl"] is not None else "open"
        pnl_pct_cell = fmt_pct(t["pnl_pct"]) if t["pnl_pct"] is not None else "—"
        status = "CLOSED" if t["closed"] else "**OPEN**"
        if t["pnl"] is not None:
            total_pnl += float(t["pnl"])
            pnl_known = True
        direction = t["direction"].upper()

        lines.append(
            f"| {t['id']} | {t['symbol']} | {direction} | "
            f"{fmt_dt(open_dt)} | {t['shares']} | "
            f"{fmt_money(trade_value)} | {fmt_price(t['fill_price'])} | "
            f"{fmt_price(t['close_price'])} | {pnl_cell} | {pnl_pct_cell} | "
            f"{t['quality_grade'] or '—'} | {status} |"
        )

    lines += [""]

    if pnl_known:
        pnl_sign = "+" if total_pnl >= 0 else ""
        lines += [f"**Total realised P&L (closed trades): {pnl_sign}{total_pnl:,.2f}**", ""]

    open_count = sum(1 for t in trades if not t["closed"])
    if open_count:
        lines += [
            f"> **{open_count} trade(s) are still open** — P&L above reflects closed trades only.",
            "",
        ]

    # ── Observations / red flags ─────────────────────────────────────────────
    observations = _build_observations(trades)
    if observations:
        lines += [
            "---",
            "",
            "## Observations & Red Flags",
            "",
        ] + observations + [""]

    # ── Individual trade detail ──────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## Individual Trade Detail",
        "",
    ]

    for t in trades:
        open_dt = utc_to_et(t["ts"])
        close_dt = utc_to_et(t["close_ts"])
        trade_value = (t["shares"] or 0) * (t["fill_price"] or 0)
        votes = parse_votes(t["votes_json"])

        dir_label = t["direction"].upper()
        status_label = f"{pnl_emoji(t['pnl'])} CLOSED" if t["closed"] else "⏳ OPEN"

        lines += [
            f"### Trade #{t['id']} — {t['symbol']} {dir_label} [{status_label}]",
            "",
            "#### Entry",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| **Date / Time** | {fmt_dt(open_dt)} |",
            f"| **Symbol** | {t['symbol']} |",
            f"| **Direction** | {dir_label} |",
            f"| **Shares** | {t['shares']} |",
            f"| **Fill Price** | {fmt_price(t['fill_price'])} |",
            f"| **Trade Value** | {fmt_money(trade_value)} |",
            f"| **Stop Price** | {fmt_price(t['stop_price'])} |",
            f"| **Target Price** | {fmt_price(t['target_price'])} |",
            "",
        ]

        lines += [
            "#### Exit",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| **Exit Time** | {fmt_dt(close_dt)} |",
            f"| **Exit Price** | {fmt_price(t['close_price'])} |",
            f"| **Time Held** | {hold_duration(open_dt, close_dt)} |",
            f"| **P&L ($)** | {fmt_money(t['pnl'])} |",
            f"| **P&L (%)** | {fmt_pct(t['pnl_pct'])} |",
            "",
        ]

        conf_str = f"{float(t['confidence']):.1%}" if t["confidence"] is not None else "—"
        avg_str = f"{float(t['avg_confirming_strength']):.4f}" if t["avg_confirming_strength"] else "—"
        override_str = ("Yes — " + str(t["override_reason"])) if t["claude_overrode_signals"] else "No"
        confirming = ", ".join(json.loads(t["confirming_strategies"] or "[]")) or "—"
        conflicting = ", ".join(json.loads(t["conflicting_strategies"] or "[]")) or "none"
        abstaining = ", ".join(json.loads(t["abstaining_strategies"] or "[]")) or "none"

        lines += [
            "#### What Triggered This Trade",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| **Signal Grade** | {grade_label(t['quality_grade'])} |",
            f"| **Confidence** | {conf_str} |",
            f"| **Confirming** | {confirming} |",
            f"| **Conflicting** | {conflicting} |",
            f"| **Abstaining** | {abstaining} |",
            f"| **Weighted Buy Score** | {t['weighted_buy_score'] or '—'} |",
            f"| **Weighted Sell Score** | {t['weighted_sell_score'] or '—'} |",
            f"| **Avg Confirming Strength** | {avg_str} |",
            f"| **Claude AI Override** | {override_str} |",
            f"| **Confirmation Mode** | {t['mode'] or '—'} |",
            "",
        ]

        if t["reasoning"]:
            # Clean up encoding artifacts
            reasoning = str(t["reasoning"]).replace("\u2713", "✓").replace("\u2717", "✗").replace("\u2014", "—")
            lines += [
                "**Bot Reasoning:**",
                "",
                f"> {reasoning}",
                "",
            ]

        if votes:
            lines += [
                "#### Strategy Votes",
                "",
                "| Strategy | Vote | Strength | Reason |",
                "|----------|------|----------|--------|",
            ]
            for v in votes:
                reason = str(v.get("reason", "")).replace("|", "/")
                lines.append(
                    f"| {v.get('strategy', '?')} | {vote_icon(v.get('vote', '?'))} "
                    f"| {float(v.get('strength', 0)):.4f} | {reason} |"
                )
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ─── Observations ─────────────────────────────────────────────────────────────

def _build_observations(trades: list[dict]) -> list[str]:
    obs: list[str] = []

    # Check for duplicate symbols
    from collections import Counter
    sym_counts = Counter(t["symbol"] for t in trades)
    dupes = {s: c for s, c in sym_counts.items() if c > 1}
    if dupes:
        for sym, count in dupes.items():
            obs.append(
                f"- **Duplicate position: {sym}** entered {count} times. "
                f"The risk gate should prevent adding to an existing open position — "
                f"review whether `get_all_positions()` was returning stale data at entry time."
            )

    # Check for missing stop/target prices
    missing_stops = [t for t in trades if t["stop_price"] is None and not t["closed"]]
    if missing_stops:
        syms = ", ".join(t["symbol"] for t in missing_stops)
        obs.append(
            f"- **Missing stop orders on open trades ({syms})** — the bracket order "
            f"placement failed at entry. These positions have no automated downside protection."
        )

    # Unrealistic VWAP deviations
    for t in trades:
        votes = parse_votes(t["votes_json"])
        for v in votes:
            if v.get("strategy") == "vwap" and "%" in str(v.get("reason", "")):
                reason = v["reason"]
                # Try to extract the percentage
                import re
                m = re.search(r"([\d.]+)%", reason)
                if m:
                    deviation = float(m.group(1))
                    if deviation > 5.0:
                        obs.append(
                            f"- **Suspicious VWAP deviation on {t['symbol']} (Trade #{t['id']}): "
                            f"{deviation:.1f}% from VWAP** — deviations above 5% suggest VWAP "
                            f"is not being reset at market open each day. This produces false "
                            f"extreme signals and should be investigated urgently."
                        )

    # EMA abstaining on all
    ema_abstain_all = all(
        "ema_cross" in json.loads(t.get("abstaining_strategies") or "[]")
        for t in trades
        if t.get("abstaining_strategies")
    )
    if ema_abstain_all and len(trades) > 1:
        obs.append(
            f"- **EMA cross abstained on every single trade** — the EMA50/200 trend filter "
            f"never confirmed any direction. This means all {len(trades)} trades were taken "
            f"with only 3/4 strategies agreeing, and the longest-timeframe trend indicator "
            f"was silent. Consider raising `MIN_SIGNALS_REQUIRED` to 4 or making EMA agreement "
            f"a hard prerequisite for entry."
        )

    # All shorts on a market-wide sell day
    short_count = sum(1 for t in trades if t["direction"] == "short")
    if short_count == len(trades) - 1 and len(trades) > 3:
        obs.append(
            f"- **{short_count}/{len(trades)} trades were SHORTS** — the bot took an almost "
            f"exclusively bearish stance for the entire session. If the market rallied intraday "
            f"this would account for the majority of the loss. Review whether the confirmation "
            f"engine is being overly sensitive to short-term MACD/VWAP dips."
        )

    # Low confidence across the board
    confidences = [float(t["confidence"]) for t in trades if t["confidence"] is not None]
    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        if avg_conf < 0.65:
            obs.append(
                f"- **Low average confidence: {avg_conf:.1%}** — all trades were marginal "
                f"signals (Grade B/C). No A-grade setups were taken. Consider adding a minimum "
                f"confidence threshold (e.g. 0.65) as an additional risk gate."
            )

    # All trades still open
    all_open = all(not t["closed"] for t in trades)
    if all_open:
        obs.append(
            "- **All trades are still recorded as OPEN in the database** — the EOD close "
            "routine successfully closes positions on Alpaca but does not call `db.close_trade()` "
            "to update the local database. This means P&L figures are missing from the review "
            "and from the daily loss limit risk check. This is a bug that needs to be fixed."
        )

    return obs


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate TRADE_REVIEW.md from trading_log.db")
    parser.add_argument("--date", help="Filter by ET date, e.g. 2026-03-17")
    parser.add_argument("--symbol", help="Filter by symbol, e.g. QQQ")
    parser.add_argument("--output", default=OUT_PATH, help=f"Output file (default: {OUT_PATH})")
    args = parser.parse_args()

    trades = load_trades(date_filter=args.date, symbol_filter=args.symbol)
    md = build_markdown(trades)

    out = Path(args.output)
    out.write_text(md, encoding="utf-8")
    print(f"Written {len(trades)} trade(s) to {out.resolve()}")

    # Quick summary to stdout
    open_count = sum(1 for t in trades if not t["closed"])
    closed_count = len(trades) - open_count
    known_pnl = sum(float(t["pnl"]) for t in trades if t["pnl"] is not None)
    print(f"  Open: {open_count}  |  Closed: {closed_count}  |  Known P&L: ${known_pnl:,.2f}")


if __name__ == "__main__":
    main()
