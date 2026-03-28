"""
Generates TRADE_REVIEW.md for a given date using Alpaca order history directly.
Usage: python alpaca_review.py --date 2026-03-26
"""
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus
from datetime import datetime, timezone, timedelta
from pathlib import Path
import argparse
from collections import defaultdict

API_KEY    = "PKFRDRWGEN7RESZF5RSBHGAEOX"
SECRET_KEY = "3XZMrGr7zw9THSWfvYtq18rrZboZCBHAnfhtW7ZW7kKB"
ET = timezone(timedelta(hours=-4))


def fetch_orders(date_str: str):
    client = TradingClient(API_KEY, SECRET_KEY, paper=True)
    day_et   = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ET)
    utc_start = day_et.astimezone(timezone.utc)
    utc_end   = (day_et + timedelta(days=1)).astimezone(timezone.utc)
    req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=200,
                           after=utc_start, until=utc_end)
    orders = [o for o in client.get_orders(req) if o.filled_at and float(o.filled_qty or 0) > 0]
    return sorted(orders, key=lambda o: o.filled_at)


def match_trades(orders):
    """FIFO match: each sell closes the most recent unmatched buy, and vice versa."""
    open_longs  = defaultdict(list)   # symbol -> [(entry_order, remaining_qty)]
    open_shorts = defaultdict(list)
    trades = []

    for o in orders:
        sym   = o.symbol
        qty   = float(o.filled_qty)
        price = float(o.filled_avg_price)
        side  = o.side.value  # "buy" or "sell"
        ts    = o.filled_at.astimezone(ET)

        if side == "buy":
            # Close shorts first
            remaining = qty
            while remaining > 0 and open_shorts[sym]:
                entry_o, entry_qty = open_shorts[sym][0]
                close_qty = min(remaining, entry_qty)
                entry_price = float(entry_o.filled_avg_price)
                pnl = (entry_price - price) * close_qty
                trades.append({
                    "symbol":      sym,
                    "direction":   "SHORT",
                    "shares":      int(close_qty),
                    "entry_price": entry_price,
                    "exit_price":  price,
                    "entry_time":  entry_o.filled_at.astimezone(ET),
                    "exit_time":   ts,
                    "pnl":         pnl,
                    "trade_value": entry_price * close_qty,
                })
                remaining -= close_qty
                if close_qty >= entry_qty:
                    open_shorts[sym].pop(0)
                else:
                    open_shorts[sym][0] = (entry_o, entry_qty - close_qty)
            if remaining > 0:
                open_longs[sym].append((o, remaining))

        elif side == "sell":
            # Close longs first
            remaining = qty
            while remaining > 0 and open_longs[sym]:
                entry_o, entry_qty = open_longs[sym][0]
                close_qty = min(remaining, entry_qty)
                entry_price = float(entry_o.filled_avg_price)
                pnl = (price - entry_price) * close_qty
                trades.append({
                    "symbol":      sym,
                    "direction":   "LONG",
                    "shares":      int(close_qty),
                    "entry_price": entry_price,
                    "exit_price":  price,
                    "entry_time":  entry_o.filled_at.astimezone(ET),
                    "exit_time":   ts,
                    "pnl":         pnl,
                    "trade_value": entry_price * close_qty,
                })
                remaining -= close_qty
                if close_qty >= entry_qty:
                    open_longs[sym].pop(0)
                else:
                    open_longs[sym][0] = (entry_o, entry_qty - close_qty)
            if remaining > 0:
                open_shorts[sym].append((o, remaining))

    # Anything still open
    open_trades = []
    for sym, entries in open_longs.items():
        for entry_o, qty in entries:
            open_trades.append({
                "symbol":      sym,
                "direction":   "LONG",
                "shares":      int(qty),
                "entry_price": float(entry_o.filled_avg_price),
                "exit_price":  None,
                "entry_time":  entry_o.filled_at.astimezone(ET),
                "exit_time":   None,
                "pnl":         None,
                "trade_value": float(entry_o.filled_avg_price) * qty,
            })
    for sym, entries in open_shorts.items():
        for entry_o, qty in entries:
            open_trades.append({
                "symbol":      sym,
                "direction":   "SHORT",
                "shares":      int(qty),
                "entry_price": float(entry_o.filled_avg_price),
                "exit_price":  None,
                "entry_time":  entry_o.filled_at.astimezone(ET),
                "exit_time":   None,
                "pnl":         None,
                "trade_value": float(entry_o.filled_avg_price) * qty,
            })

    return trades + open_trades


def build_markdown(date_str: str, trades: list) -> str:
    now_et = datetime.now(timezone.utc).astimezone(ET)
    closed = [t for t in trades if t["pnl"] is not None]
    open_t = [t for t in trades if t["pnl"] is None]
    total_pnl = sum(t["pnl"] for t in closed)

    lines = [
        "# Trade Review",
        "",
        f"> Generated: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}  ",
        f"> Source: Alpaca paper account (live orders)  ",
        f"> Session: **{date_str}**  ",
        f"> Total trades in this report: **{len(trades)}**",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| # | Symbol | Dir | Entry (ET) | Exit (ET) | Shares | Trade Value | Entry Price | Exit Price | P&L | P&L % | Status |",
        "|---|--------|-----|-----------|-----------|--------|-------------|-------------|------------|-----|-------|--------|",
    ]

    for i, t in enumerate(trades, 1):
        entry_str = t["entry_time"].strftime("%H:%M:%S")
        exit_str  = t["exit_time"].strftime("%H:%M:%S") if t["exit_time"] else "—"
        pnl_str   = f"${t['pnl']:+,.2f}" if t["pnl"] is not None else "open"
        pnl_pct   = f"{(t['pnl'] / t['trade_value'] * 100):+.2f}%" if t["pnl"] is not None else "—"
        exit_p    = f"${t['exit_price']:.4f}" if t["exit_price"] else "—"
        status    = "CLOSED" if t["pnl"] is not None else "**OPEN**"
        lines.append(
            f"| {i} | {t['symbol']} | {t['direction']} | {entry_str} | {exit_str} | "
            f"{t['shares']} | ${t['trade_value']:,.2f} | ${t['entry_price']:.4f} | "
            f"{exit_p} | {pnl_str} | {pnl_pct} | {status} |"
        )

    lines += [
        "",
        f"**Total realised P&L (closed trades): ${total_pnl:+,.2f}**",
        "",
    ]

    if open_t:
        lines.append(f"> **{len(open_t)} trade(s) still open** — P&L above reflects closed trades only.")
        lines.append("")

    # ── P&L by symbol ────────────────────────────────────────────────────────
    lines += ["---", "", "## P&L by Symbol", "", "| Symbol | Trades | Closed | Total P&L | Avg P&L |", "|--------|--------|--------|-----------|---------|"]
    from collections import defaultdict
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t["symbol"]].append(t)
    for sym, ts in sorted(by_sym.items(), key=lambda x: -sum(t["pnl"] for t in x[1] if t["pnl"] is not None)):
        sym_closed = [t for t in ts if t["pnl"] is not None]
        sym_pnl    = sum(t["pnl"] for t in sym_closed)
        avg_pnl    = sym_pnl / len(sym_closed) if sym_closed else 0
        lines.append(f"| {sym} | {len(ts)} | {len(sym_closed)} | ${sym_pnl:+,.2f} | ${avg_pnl:+,.2f} |")
    lines.append("")

    # ── Individual trade detail ───────────────────────────────────────────────
    lines += ["---", "", "## Individual Trade Detail", ""]

    for i, t in enumerate(trades, 1):
        status_icon = "✅ CLOSED" if t["pnl"] is not None else "⏳ OPEN"
        pnl_str   = f"${t['pnl']:+,.2f}" if t["pnl"] is not None else "—"
        pnl_pct   = f"{(t['pnl'] / t['trade_value'] * 100):+.2f}%" if t["pnl"] is not None else "—"
        held      = "—"
        if t["entry_time"] and t["exit_time"]:
            delta = t["exit_time"] - t["entry_time"]
            s = int(delta.total_seconds())
            h, r = divmod(s, 3600); m, sec = divmod(r, 60)
            held = (f"{h}h " if h else "") + (f"{m}m " if m else "") + f"{sec}s"

        lines += [
            f"### Trade #{i} — {t['symbol']} {t['direction']} [{status_icon}]",
            "",
            "#### Entry",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| **Date / Time** | {t['entry_time'].strftime('%Y-%m-%d %H:%M:%S ET')} |",
            f"| **Symbol** | {t['symbol']} |",
            f"| **Direction** | {t['direction']} |",
            f"| **Shares** | {t['shares']} |",
            f"| **Fill Price** | ${t['entry_price']:.4f} |",
            f"| **Trade Value** | ${t['trade_value']:,.2f} |",
            "",
            "#### Exit",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| **Exit Time** | {t['exit_time'].strftime('%Y-%m-%d %H:%M:%S ET') if t['exit_time'] else '—'} |",
            f"| **Exit Price** | ${t['exit_price']:.4f} |" if t["exit_price"] else "| **Exit Price** | — |",
            f"| **Time Held** | {held} |",
            f"| **P&L ($)** | {pnl_str} |",
            f"| **P&L (%)** | {pnl_pct} |",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-03-26", help="ET date YYYY-MM-DD")
    args = parser.parse_args()

    print(f"Fetching orders for {args.date}...")
    orders = fetch_orders(args.date)
    print(f"  {len(orders)} filled orders found")

    trades = match_trades(orders)
    print(f"  {len(trades)} round-trip trades matched")

    md = build_markdown(args.date, trades)
    Path("TRADE_REVIEW.md").write_text(md, encoding="utf-8")
    closed = [t for t in trades if t["pnl"] is not None]
    total  = sum(t["pnl"] for t in closed)
    print(f"  Written to TRADE_REVIEW.md")
    print(f"  Closed trades: {len(closed)}  |  Total P&L: ${total:+,.2f}")


if __name__ == "__main__":
    main()
