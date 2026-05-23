"""
Fetches 1Min bars for all watchlist symbols on a given date and runs all four
strategies + confirmation engine across every bar, printing a timeline of every
signal that fired at Grade B or above.

Usage: python analyse_day.py --date 2026-04-13
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

API_KEY    = config.ALPACA_API_KEY
SECRET_KEY = config.ALPACA_SECRET_KEY
ET = timezone(timedelta(hours=-4))
WARMUP = 250  # bars needed before signals are reliable


def fetch_bars(symbols, date_str):
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    day_et = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ET)
    # Fetch from 2 days before to ensure enough warmup bars
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


def analyse(date_str):
    symbols = config.WATCHLIST
    print(f"\nFetching 1Min bars for {len(symbols)} symbols around {date_str}...\n")
    all_bars = fetch_bars(symbols, date_str)

    day_et    = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ET)
    day_start = day_et.astimezone(timezone.utc)
    day_end   = (day_et + timedelta(days=1)).astimezone(timezone.utc)

    signals_found = []

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

        # Only iterate over bars that fall on the target date
        day_bars = df[(df.index >= day_start) & (df.index < day_end)]
        if day_bars.empty:
            print(f"  {sym}: no bars on {date_str}")
            continue

        print(f"  {sym}: {len(day_bars)} bars on {date_str} ({len(df)} total with warmup)")

        for i, ts in enumerate(day_bars.index):
            loc = df.index.get_loc(ts)
            if loc < WARMUP:
                continue  # not enough warmup history

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
            if grade not in ("A", "B"):
                continue

            direction = report["direction"]
            price = float(window["close"].iloc[-1])
            ts_et = ts.astimezone(ET).strftime("%H:%M")

            signals_found.append({
                "time_et": ts_et,
                "symbol": sym,
                "direction": direction.upper(),
                "grade": grade,
                "votes": report["signal_count"],
                "price": price,
                "macd": macd["signal"],
                "vwap": vwap["signal"],
                "ema": ema["signal"],
                "pa": pa["signal"],
            })

    sep = "-" * 90
    print(f"\n{sep}")
    print(f"  SIGNALS FIRED ON {date_str} (Grade A/B confirmed only)")
    print(sep)

    if not signals_found:
        print("  No Grade A/B signals fired on this date.")
    else:
        # Deduplicate — only show first signal per symbol per direction
        seen = set()
        unique = []
        for s in signals_found:
            key = (s["symbol"], s["direction"])
            if key not in seen:
                seen.add(key)
                unique.append(s)

        print(f"  {'Time':>6}  {'Symbol':<6}  {'Dir':<5}  {'Grade'}  {'Votes':<6}  {'Price':>8}  MACD    VWAP    EMA     PA")
        print(f"  {'--':>6}  {'------':<6}  {'-----':<5}  {'-----'}  {'------':<6}  {'--------':>8}  {'------'}  {'------'}  {'------'}  {'------'}")
        for s in unique:
            print(
                f"  {s['time_et']:>6}  {s['symbol']:<6}  {s['direction']:<5}  "
                f"  {s['grade']}    {s['votes']:<6}  ${s['price']:>7.2f}  "
                f"{s['macd']:<7} {s['vwap']:<7} {s['ema']:<7} {s['pa']:<6}"
            )

    print(f"\n  Total unique confirmed signals: {len(seen) if signals_found else 0}")
    print(f"{sep}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Date to analyse (YYYY-MM-DD)")
    args = parser.parse_args()
    analyse(args.date)
