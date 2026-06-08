"""
Test the Claude AI decision layer on a single historical day.

Replays one day of 1Min bars across the watchlist, runs the four strategies +
confirmation engine exactly like the live bot, and at each confirmed signal
calls Claude (get_trade_decision) so you can compare the confirmation-engine
decision SIDE-BY-SIDE with what the AI would decide.

This is the only way to evaluate USE_AI=true without running the bot live,
since the live-backtest engine uses the confirmation engine directly and never
calls Claude.

Usage:
  python test_ai_day.py --date 2026-06-05
  python test_ai_day.py --date 2026-06-05 --min-grade C   # include Grade C too
  python test_ai_day.py --date 2026-06-05 --symbol NVDA,XLK

Note: calls the Anthropic API once per unique confirmed signal (deduped to the
first signal per symbol+direction), so cost is small. Requires ANTHROPIC_API_KEY
in .env.
"""
import argparse
from datetime import datetime, timezone, timedelta

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

import config
from strategies import (
    get_macd_signal,
    get_vwap_signal,
    get_ema_signal,
    get_price_action_signal,
    evaluate_confirmation,
)
from claude_brain import get_trade_decision

API_KEY    = config.ALPACA_API_KEY
SECRET_KEY = config.ALPACA_SECRET_KEY
ET = timezone(timedelta(hours=-4))
WARMUP = 250
_GRADE_RANK = {"A": 3, "B": 2, "C": 1, "F": 0}


def fetch_bars(symbols, date_str):
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    day_et = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ET)
    start = (day_et - timedelta(days=5)).astimezone(timezone.utc)
    end   = (day_et + timedelta(days=1)).astimezone(timezone.utc)
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed="iex",
    )
    bars = client.get_stock_bars(req).df
    if isinstance(bars.index, pd.MultiIndex):
        bars = bars.reset_index(level=0)
        bars.index = pd.to_datetime(bars.index, utc=True)
    return bars


def _build_bar_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    last = df.iloc[-1]
    today = df[df.index.date == df.index[-1].date()]
    first_today = today.iloc[0] if len(today) > 0 else last
    avg_vol = df["volume"].tail(20).mean()
    return {
        "current_price": float(last["close"]),
        "daily_open": float(first_today["open"]),
        "daily_high": float(today["high"].max()),
        "daily_low": float(today["low"].min()),
        "daily_change_pct": (float(last["close"]) - float(first_today["open"])) / float(first_today["open"]) * 100,
        "avg_volume": float(avg_vol),
        "volume_ratio": float(last["volume"]) / float(avg_vol) if avg_vol > 0 else 1.0,
    }


def run(date_str, min_grade, symbols):
    min_rank = _GRADE_RANK.get(min_grade.upper(), 2)
    print(f"\nFetching 1Min bars for {len(symbols)} symbols around {date_str}...\n")
    all_bars = fetch_bars(symbols, date_str)

    day_et    = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ET)
    day_start = day_et.astimezone(timezone.utc)
    day_end   = (day_et + timedelta(days=1)).astimezone(timezone.utc)

    seen = set()
    results = []

    for sym in symbols:
        if isinstance(all_bars.index, pd.MultiIndex):
            df = all_bars.xs(sym, level="symbol") if sym in all_bars.index.get_level_values("symbol") else pd.DataFrame()
        else:
            df = all_bars[all_bars["symbol"] == sym].drop(columns=["symbol"], errors="ignore")

        if df.empty:
            print(f"  {sym}: no data")
            continue

        df.index = pd.to_datetime(df.index, utc=True)
        df = df.sort_index()
        day_bars = df[(df.index >= day_start) & (df.index < day_end)]
        if day_bars.empty:
            print(f"  {sym}: no bars on {date_str}")
            continue

        print(f"  {sym}: scanning {len(day_bars)} bars on {date_str}...")

        for ts in day_bars.index:
            loc = df.index.get_loc(ts)
            if loc < WARMUP:
                continue
            window = df.iloc[: loc + 1]
            try:
                macd = get_macd_signal(window)
                vwap = get_vwap_signal(window)
                ema  = get_ema_signal(window)
                pa   = get_price_action_signal(window)
            except Exception:
                continue

            report = evaluate_confirmation(
                macd_signal=macd,
                vwap_signal=vwap,
                ema_signal=ema,
                price_action_signal=pa,
                min_required=config.MIN_SIGNALS_REQUIRED,
                min_strength=config.MIN_SIGNAL_STRENGTH,
                mode=config.CONFIRMATION_MODE,
                allow_shorts=config.ALLOW_SHORTS,
            )

            if not report["confirmed"]:
                continue
            grade = report["quality"]
            if _GRADE_RANK.get(grade, 0) < min_rank:
                continue
            direction = report["direction"]
            if direction not in ("buy", "sell"):
                continue

            key = (sym, direction)
            if key in seen:
                continue
            seen.add(key)

            # Confirmation-engine decision (what the bot does with USE_AI=false)
            conf_action = direction  # engine would act on the confirmed direction

            # Claude decision (USE_AI=true)
            bar_summary = _build_bar_summary(window)
            ts_et = ts.astimezone(ET).strftime("%H:%M")
            print(f"    -> calling Claude for {sym} {direction.upper()} (Grade {grade}) @ {ts_et} ET...")
            try:
                ai = get_trade_decision(
                    symbol=sym,
                    bar_summary=bar_summary,
                    confirmation_report=report,
                    portfolio_context={"buying_power": 100000, "portfolio_value": 100000, "open_positions": 0},
                )
            except Exception as exc:
                print(f"       Claude error: {exc}")
                continue

            results.append({
                "time_et": ts_et,
                "symbol": sym,
                "grade": grade,
                "votes": report["signal_count"],
                "engine_action": conf_action.upper(),
                "ai_action": ai.get("action", "?").upper(),
                "ai_conf": ai.get("confidence", 0.0),
                "ai_override": ai.get("overriding_confirmation", False),
                "ai_reason": ai.get("reasoning", ""),
            })

    sep = "-" * 100
    print(f"\n{sep}")
    print(f"  AI vs CONFIRMATION-ENGINE comparison — {date_str} (Grade >= {min_grade.upper()})")
    print(sep)

    if not results:
        print("  No confirmed signals at/above the grade threshold on this date.")
        print(f"{sep}\n")
        return

    agree = 0
    differ = 0
    for r in results:
        same = (r["engine_action"] == r["ai_action"])
        agree += same
        differ += (not same)
        flag = "AGREE " if same else "DIFFER"
        ovr = " [OVERRIDE]" if r["ai_override"] else ""
        print(
            f"  {r['time_et']:>5} ET  {r['symbol']:<5}  Grade {r['grade']} ({r['votes']})  "
            f"engine={r['engine_action']:<4}  AI={r['ai_action']:<4} conf={r['ai_conf']:.2f}  {flag}{ovr}"
        )
        print(f"           AI reasoning: {r['ai_reason']}")

    print(sep)
    print(f"  Signals evaluated: {len(results)}   AI agreed: {agree}   AI differed: {differ}")
    print(f"{sep}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Date to test (YYYY-MM-DD)")
    parser.add_argument("--min-grade", default="B", choices=["A", "B", "C"],
                        help="Minimum confirmation grade to evaluate (default B)")
    parser.add_argument("--symbol", default=None,
                        help="Comma-separated symbols (default: WATCHLIST from .env)")
    args = parser.parse_args()

    syms = [s.strip().upper() for s in args.symbol.split(",")] if args.symbol else config.WATCHLIST
    run(args.date, args.min_grade, syms)
