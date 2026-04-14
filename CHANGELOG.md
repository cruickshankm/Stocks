# Strategy & Config Changelog

All strategy refinements, config changes, and bug fixes are recorded here in reverse chronological order.
Each entry includes a full config snapshot so any version can be exactly reproduced.

---

## How to use this file

- **Add an entry every time you change `.env` settings or modify strategy logic.**
- Copy the `### Config snapshot` block from the previous entry, paste it into the new one, and update only the lines that changed.
- Mark changed lines with `← changed` so diffs are easy to spot.
- Record backtest results before and after each change so you know if it helped.

---

## [2026-04-14] FULL OPTIMISATION SESSION SUMMARY

**Author:** matthew  
**Session date:** 2026-04-14  
**Method:** 60-day live-style backtest (2026-02-12 to 2026-04-13, $100k starting capital, 1Min bars)  
**Base command:** `python main.py --live-backtest --start 2026-02-12 --capital 100000`

---

### What we were trying to do
Starting from the baseline config (Grade B signals, full 11-symbol watchlist, 2% stop / 4% target), we ran 8 systematic backtests changing one variable at a time to find the best combination. Goal was to improve daily average P&L toward $1k/day.

---

### Full test results

| # | What changed vs previous | Return | Sharpe | Max DD | Trades | Win% | PF |
|---|---|---|---|---|---|---|---|
| Baseline | Grade B, full watchlist, no filter | +7.04% | 7.01 | 2.07% | 90 | 44.4% | 1.47 |
| 1 | + Trend filter ON | +6.72% | 7.42 | 2.07% | 81 | 44.4% | 1.50 |
| 2 | + Trimmed watchlist (removed USO,GDXJ,SLV,TLT,SPY) | +8.68% | 15.33 | 1.18% | 50 | 56.0% | 2.29 |
| 3 | Trimmed + trend filter ON | +7.07% | 13.85 | 1.18% | 45 | 53.3% | 2.11 |
| 4 | Trimmed + 5% target | +11.90% | 18.18 | 1.18% | 49 | 55.1% | 2.76 |
| 5 | Trimmed + 5% target + 1.5% stop | +10.31% | 16.74 | 1.56% | 50 | 48.0% | 2.73 |
| **6 🏆** | **Trimmed + 6% target (2% stop)** | **+14.43%** | **20.98** | **1.18%** | **45** | **55.6%** | **3.35** |
| 7 | Trimmed + 6% target + signal strength 0.65 | -0.47% | -3.45 | 1.19% | 12 | 25.0% | 0.82 |
| 8 | Trimmed + 5% target + softer VWAP (0.25/2.0) | +6.53% | 15.56 | 0.89% | 31 | 48.4% | 2.35 |

---

### Key findings

**1. Trimming the watchlist was the single biggest improvement**
Removing USO, GDXJ, SLV, TLT, SPY improved return from +7.04% → +8.68%, win rate from 44.4% → 56%, Sharpe from 7.01 → 15.33, and halved max drawdown (2.07% → 1.18%). These symbols were generating losing clusters — particularly USO (26.7% win rate, -$731), GDXJ (33.3%, -$516), SLV (30.8%, -$342). TLT and SPY generated zero trades in the entire 60-day period.

**2. Wider take-profit consistently improves results**
4% → 5% → 6% each added meaningful return without hurting win rate or drawdown. At 6% the wins average ~$850 instead of ~$550. This works because the 6 remaining symbols (GDX, UCO, QQQ, IWM, XLE, UNG) make large enough intraday moves to reach 6%. Win rate stayed at 55-56% across 4%/5%/6% targets — the moves are real.

**3. Do not touch the stop loss**
Tightening to 1.5% reduced return from +11.90% → +10.31% and win rate from 55.1% → 48%. The 2% stop is the right amount of breathing room. Tighter stops get clipped by normal price noise and then the trade recovers without us.

**4. Trend filter consistently hurts in volatile markets**
Tested on both full and trimmed watchlists — both times it hurt return and Sharpe. The March/April 2026 period was highly directional with fast reversals (tariff news), so the filter was reading the wrong direction and blocking winning trades. Note: the March 28 commit showed it helped on a calmer 3-month window — may be worth re-testing when market conditions normalise.

**5. Signal strength threshold must stay at 0.55**
Raising to 0.65 reduced 60-day trade count from 49 to 12 and win rate to 25% — catastrophic. The strategies rarely produce signals above 0.65 across all 3 agreeing strategies. When they do, the signal may already be late.

**6. VWAP settings at 0.15/1.5 are correct**
Softening to 0.25/2.0 cut trade count from 49 to 31 — VWAP became too picky and missed valid entries. The current settings are well-calibrated for 1Min bars.

---

### What to test next (when resuming)

1. **7% take-profit** — the 4→5→6% trend suggests 7% may also improve. Risk is more EOD liquidations cutting targets short.
2. **Longer validation period** — run 90-day or 6-month backtest with the winning config to confirm it's not period-specific.
3. **Add 1-2 more symbols to the trimmed list** — currently 6 symbols generating ~45 trades/60 days (~0.75/day). Adding UNG (100% win rate), GDXJ (if re-tested), or a non-commodity symbol like NVDA or AAPL could add signal diversity without the correlation problem.
4. **Trend filter on calmer period** — re-test TREND_FILTER_ENABLED=true on a 3-month window with less news-driven volatility.

---

### Active config after this session

```
WATCHLIST=GDX,UCO,QQQ,IWM,XLE,UNG
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.06
MIN_GRADE=B
MIN_SIGNAL_STRENGTH=0.55
MIN_SIGNALS_REQUIRED=3
TREND_FILTER_ENABLED=false
MACD_FAST=5 / MACD_SLOW=13 / MACD_SIGNAL=6
VWAP_MIN_DEVIATION_PCT=0.15 / VWAP_SENSITIVITY=1.5
EMA_FAST=9 / EMA_SLOW=21
BAR_TIMEFRAME=1Min / BAR_LIMIT=500
MAX_OPEN_POSITIONS=6 / MAX_POSITION_SIZE=0.166
```

### Live bot commands
```bash
# Run live bot
python main.py

# 60-day backtest (current winning config)
python main.py --live-backtest --start 2026-02-12 --capital 100000

# Single day signal analysis
python analyse_day.py --date 2026-04-13

# Trade review for a specific session
python alpaca_review.py --date 2026-04-13
```

---

## [2026-04-14] 6% take-profit target (follow-up optimisation)

**Author:** matthew

### Changes

#### .env
- `TAKE_PROFIT_PCT`: `0.05` → `0.06`

### Reason
Follow-up 3-test run on the trimmed watchlist config. 6% target continued the improvement trend from 4%→5%. Win rate stayed at 55.6% confirming moves are large enough to reach the wider target. Softer VWAP (0.25/2.0) cut too many trades. Higher signal strength (0.65) was catastrophic — only 12 trades, 25% win rate.

| Test | Config | Return | Sharpe | Max DD | Trades | Win% | PF |
|---|---|---|---|---|---|---|---|
| **6 🏆** | **+ 6% target** | **+14.43%** | **20.98** | **1.18%** | **45** | **55.6%** | **3.35** |
| 7 | Signal strength 0.65 | -0.47% | -3.45 | 1.19% | 12 | 25.0% | 0.82 |
| 8 | Softer VWAP (0.25/2.0) | +6.53% | 15.56 | 0.89% | 31 | 48.4% | 2.35 |

### Config snapshot

```
WATCHLIST=GDX,UCO,QQQ,IWM,XLE,UNG
MAX_POSITION_SIZE=0.166
MAX_PORTFOLIO_RISK=0.07
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.06                      ← changed from 0.05
MAX_OPEN_POSITIONS=6
MAX_PYRAMID_ENTRIES=1
MIN_SIGNALS_REQUIRED=3
MIN_SIGNAL_STRENGTH=0.55
MIN_GRADE=B
ALLOW_SHORTS=true
CONFIRMATION_MODE=strict
MACD_FAST=5
MACD_SLOW=13
MACD_SIGNAL=6
VWAP_MIN_DEVIATION_PCT=0.15
VWAP_SENSITIVITY=1.5
EMA_FAST=9
EMA_SLOW=21
TREND_FILTER_ENABLED=false
TREND_FILTER_PERIOD=200
BAR_TIMEFRAME=1Min
BAR_LIMIT=500
SCAN_INTERVAL_SECONDS=60
```

### Backtest result (60-day, $100k)
| Metric | Value |
|---|---|
| Total return | +14.43% |
| Total P&L | $+14,425.73 |
| Sharpe ratio | 20.98 |
| Max drawdown | 1.18% |
| Win rate | 55.6% |
| Profit factor | 3.35 |
| Total trades | 45 |

---

## [2026-04-14] Watchlist trim + wider take-profit (5-test optimisation run)

**Author:** matthew

### Changes

#### .env
- `WATCHLIST`: removed USO, GDXJ, SLV, TLT, SPY — all were "Avoid" or generated zero trades in 60-day backtest
- `TAKE_PROFIT_PCT`: `0.04` → `0.05`

### Reason
Ran 5 systematic 60-day live backtests (2026-02-12 to 2026-04-13, $100k) isolating one variable at a time. Results:

| Test | Config | Return | Sharpe | Max DD | Win% |
|---|---|---|---|---|---|
| Baseline | Grade B, full watchlist, no filter | +7.04% | 7.01 | 2.07% | 44.4% |
| 1 | + Trend filter ON | +6.72% | 7.42 | 2.07% | 44.4% |
| 2 | + Trimmed watchlist | +8.68% | 15.33 | 1.18% | 56.0% |
| 3 | + Trimmed + trend filter ON | +7.07% | 13.85 | 1.18% | 53.3% |
| **4 (winner)** | **+ Trimmed + 5% target** | **+11.90%** | **18.18** | **1.18%** | **55.1%** |
| 5 | + Trimmed + 5% target + 1.5% stop | +10.31% | 16.74 | 1.56% | 48.0% |

Key findings:
- Trimming the watchlist was the single biggest improvement — win rate jumped from 44.4% → 56%, Sharpe more than doubled, max drawdown dropped from 2.07% → 1.18%
- Widening the target to 5% added another +3.22% return (winners now average ~$700 instead of ~$550)
- Tightening the stop to 1.5% hurt — more stops triggered on normal noise, win rate dropped to 48%
- Trend filter consistently hurts on this volatile period — confirmed across both full and trimmed watchlists

### Config snapshot

```
WATCHLIST=GDX,UCO,QQQ,IWM,XLE,UNG       ← changed (removed USO,GDXJ,SLV,TLT,SPY)
MAX_POSITION_SIZE=0.166
MAX_PORTFOLIO_RISK=0.07
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.05                      ← changed from 0.04
MAX_OPEN_POSITIONS=6
MAX_PYRAMID_ENTRIES=1
MIN_SIGNALS_REQUIRED=3
MIN_SIGNAL_STRENGTH=0.55
MIN_GRADE=B
ALLOW_SHORTS=true
CONFIRMATION_MODE=strict
MACD_FAST=5
MACD_SLOW=13
MACD_SIGNAL=6
VWAP_MIN_DEVIATION_PCT=0.15
VWAP_SENSITIVITY=1.5
EMA_FAST=9
EMA_SLOW=21
TREND_FILTER_ENABLED=false
TREND_FILTER_PERIOD=200
BAR_TIMEFRAME=1Min
BAR_LIMIT=500
SCAN_INTERVAL_SECONDS=60
```

### Backtest result (60-day, $100k)
| Metric | Value |
|---|---|
| Total return | +11.90% |
| Total P&L | $+11,902.76 |
| Sharpe ratio | 18.18 |
| Max drawdown | 1.18% |
| Win rate | 55.1% |
| Profit factor | 2.76 |
| Total trades | 49 |

---

## [2026-04-12] Enable trend pre-filter

**Author:** matthew

### Changes

#### .env
- `TREND_FILTER_ENABLED`: `false` → `true`

### Reason
30-day live backtest (2026-03-13 to 2026-04-12, $100k) showed 5 consecutive stop hits on March 13 — all entries going against a strong directional move. The trend filter blocks signals that oppose the macro session trend (price vs 200-bar EMA). The March 28 commit showed this setting improved the 3-month backtest from +6.81% → +9.72%.

### Backtest before (trend filter OFF)
| Metric | Value |
|---|---|
| Total return | +5.32% |
| Total P&L | $+5,315.18 |
| Sharpe ratio | 10.74 |
| Max drawdown | 1.49% |
| Win rate | 52.2% |
| Profit factor | 1.83 |
| Total trades | 46 |

### Config snapshot

```
WATCHLIST=USO,GDX,GDXJ,QQQ,IWM,TLT,UCO,SLV,XLE,UNG,SPY
MAX_POSITION_SIZE=0.166
MAX_PORTFOLIO_RISK=0.07
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.04
MAX_OPEN_POSITIONS=6
MAX_PYRAMID_ENTRIES=1
MIN_SIGNALS_REQUIRED=3
MIN_SIGNAL_STRENGTH=0.55
MIN_GRADE=B
ALLOW_SHORTS=true
CONFIRMATION_MODE=strict
MACD_FAST=5
MACD_SLOW=13
MACD_SIGNAL=6
VWAP_MIN_DEVIATION_PCT=0.15
VWAP_SENSITIVITY=1.5
EMA_FAST=9
EMA_SLOW=21
TREND_FILTER_ENABLED=true       ← changed from false
TREND_FILTER_PERIOD=200
BAR_TIMEFRAME=1Min
BAR_LIMIT=500
SCAN_INTERVAL_SECONDS=60
```

### Backtest after (trend filter ON)
| Metric | Value |
|---|---|
| Total return | +4.48% |
| Total P&L | $+4,481.13 |
| Sharpe ratio | 9.91 |
| Max drawdown | 1.49% |
| Win rate | 52.4% |
| Profit factor | 1.74 |
| Total trades | 42 |

### Verdict: REVERTED
Filter hurt performance on this window (-0.84%). Blocked 2 winning UCO trades during a volatile whipsawing period (March/April 2026 tariff news). The trend filter may still help over longer, calmer periods — re-test on a 3-month window before re-enabling. `TREND_FILTER_ENABLED` set back to `false`.

---

## [2026-04-12] Pyramid cap + min-grade CLI fix + analyse_day utility

**Author:** matthew  
**Commit:** `dcf2d02`

### Changes

#### risk_gate.py — Pyramid entry cap
- Added `check_pyramid_limit()`: blocks add-ons to an existing position once `MAX_PYRAMID_ENTRIES` is reached
- `run_risk_gate()` now accepts `pyramid_count` parameter (count of entries into this symbol today)
- New check runs as step 4b, between position-limits and position-size checks

#### main.py — Pyramid counter + CLI default fix
- Added `_symbol_entries_today: dict[str, int]` module-level counter, reset each day at midnight
- `scan_symbol()` increments counter on each confirmed fill, passes count to `run_risk_gate()`
- Fixed `--min-grade` CLI flag: was hardcoded to `"C"`, now defaults to `config.MIN_GRADE` (reads from `.env`)

#### New utility: analyse_day.py
- Fetches 1Min bars for all watchlist symbols on a given date with full warmup history
- Runs all 4 strategies + confirmation engine across every bar on that date
- Prints a timeline of every Grade A/B/C confirmed signal that fired — symbol, time, direction, which strategies agreed, price
- Used to diagnose live session vs backtest discrepancies
- Usage: `python analyse_day.py --date 2026-04-13`

### Config snapshot

```
WATCHLIST=USO,GDX,GDXJ,QQQ,IWM,TLT,UCO,SLV,XLE,UNG,SPY
MAX_POSITION_SIZE=0.166
MAX_PORTFOLIO_RISK=0.07
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.04
MAX_OPEN_POSITIONS=6
MAX_PYRAMID_ENTRIES=1          ← new (1 = no add-ons to existing positions)
MIN_SIGNALS_REQUIRED=3
MIN_SIGNAL_STRENGTH=0.55
MIN_GRADE=B
ALLOW_SHORTS=true
CONFIRMATION_MODE=strict
MACD_FAST=5
MACD_SLOW=13
MACD_SIGNAL=6
VWAP_MIN_DEVIATION_PCT=0.15
VWAP_SENSITIVITY=1.5
EMA_FAST=9
EMA_SLOW=21
TREND_FILTER_ENABLED=false
TREND_FILTER_PERIOD=200
BAR_TIMEFRAME=1Min
BAR_LIMIT=500
SCAN_INTERVAL_SECONDS=60
```

### Backtest result
30-day live backtest (2026-03-13 to 2026-04-12, $100k) — run with trend filter OFF:
| Metric | Value |
|---|---|
| Total return | +5.32% |
| Total P&L | $+5,315.18 |
| Sharpe ratio | 10.74 |
| Max drawdown | 1.49% |
| Win rate | 52.2% |
| Profit factor | 1.83 |
| Total trades | 46 |

---

## [2026-03-29 14:50 ACST] Fix daily P&L source + reduce live BAR_LIMIT

**Author:** matthew  
**Commit:** `88d7293`

### Problem
Daily loss limit was effectively disabled. `risk_gate.py` was reading P&L from `trading_log.db`, which only gets updated at EOD liquidation. Bracket stop/target fills mid-session were invisible to it, so the -3% daily loss hard stop was never triggering.

### Changes

#### main.py — Daily P&L source
- `scan_symbol()`: `daily_pnl` now read from Alpaca account equity delta (`equity - last_equity`) instead of local DB
- Falls back to `db.get_daily_pnl()` if the API call fails

#### .env — BAR_LIMIT reduced
- `BAR_LIMIT`: `23400` → `500`
- Was fetching 3 months of 1-min bars per symbol on every 60-second tick (8 × 23,400 data points/scan). Strategies need at most 390 bars (VWAP) + 200 (trend EMA). 500 covers all indicators with headroom and makes scans fast.

### Config snapshot

```
WATCHLIST=USO,GDX,GDXJ,QQQ,IWM,TLT,UCO,SLV,XLE,UNG,SPY
MAX_POSITION_SIZE=0.166
MAX_PORTFOLIO_RISK=0.07
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.04
MAX_OPEN_POSITIONS=6
MIN_SIGNALS_REQUIRED=3
MIN_SIGNAL_STRENGTH=0.55
MIN_GRADE=B
ALLOW_SHORTS=true
CONFIRMATION_MODE=strict
MACD_FAST=5
MACD_SLOW=13
MACD_SIGNAL=6
VWAP_MIN_DEVIATION_PCT=0.15
VWAP_SENSITIVITY=1.5
EMA_FAST=9
EMA_SLOW=21
TREND_FILTER_ENABLED=false
TREND_FILTER_PERIOD=200
BAR_TIMEFRAME=1Min
BAR_LIMIT=500                  ← changed from 23400
SCAN_INTERVAL_SECONDS=60
```

### Backtest result
> *Not recorded at time of change*

---

## [2026-03-28 11:06 ACST] Trend pre-filter + pyramiding fix + watchlist optimisation

**Author:** matthew  
**Commit:** `8371eca`

### Motivation
3-month backtest showed trades being taken against the prevailing intraday trend and pyramiding entries leaving positions unprotected when bracket orders were cancelled.

### Changes

#### strategies.py — Trend pre-filter
- Added `get_trend_direction(bars, period)`: computes a long-period EMA and returns `bull` / `bear` / `neutral`
- Default period: 200 × 1Min bars ≈ 3.3 hours of intraday context

#### main.py + backtester.py + live_backtest.py — Wire trend filter
- Signals opposing the session macro trend are blocked before the risk gate
- Controlled by `TREND_FILTER_ENABLED` and `TREND_FILTER_PERIOD` in `.env`

#### executor.py — Pyramiding fix
- Fixed bug where existing stop/limit orders were cancelled on pyramid entries, leaving open positions unprotected
- Added `cancel_orphaned_orders_for_symbol()`: selectively cancels only stale bracket orders whose parent position no longer exists
- `execute_trade()` now accepts `existing_position` param and routes to the correct cancellation function

#### New utility: alpaca_review.py
- Fetches Alpaca order history for a given date and generates `TRADE_REVIEW.md` without requiring the local `trading_log.db`

### Config snapshot

```
WATCHLIST=USO,GDX,GDXJ,QQQ,IWM,TLT,UCO,SLV,XLE,UNG,SPY  ← changed from AAPL,MSFT,NVDA,SPY
MAX_POSITION_SIZE=0.166                                    ← changed from 0.10
MAX_PORTFOLIO_RISK=0.07                                    ← changed from 0.02
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.04
MAX_OPEN_POSITIONS=6                                       ← changed from 5
MIN_SIGNALS_REQUIRED=3
MIN_SIGNAL_STRENGTH=0.55
MIN_GRADE=B                                                ← changed from C
ALLOW_SHORTS=true
CONFIRMATION_MODE=strict
MACD_FAST=5                                                ← changed from 12
MACD_SLOW=13                                               ← changed from 26
MACD_SIGNAL=6                                              ← changed from 9
VWAP_MIN_DEVIATION_PCT=0.15                                ← changed from 0.5
VWAP_SENSITIVITY=1.5                                       ← changed from 3.0
EMA_FAST=9                                                 ← changed from 50
EMA_SLOW=21                                                ← changed from 200
TREND_FILTER_ENABLED=false                                 ← new
TREND_FILTER_PERIOD=200                                    ← new
BAR_TIMEFRAME=1Min                                         ← changed from 1Hour
BAR_LIMIT=23400
SCAN_INTERVAL_SECONDS=60
```

### Backtest result (3-month, $100k starting capital)
| Metric | Before | After |
|---|---|---|
| Total return | +6.81% | +9.72% |
| Sharpe ratio | — | 6.60 |
| Max drawdown | — | 6.94% |

---

## [2026-03-21 16:35 ACST] Initial build

**Author:** matthew  
**Commit:** `1020616`

### Summary
Full bot built from scratch. Core components:
- `strategies.py`: MACD, VWAP, EMA cross, Price Action + `SignalConfirmationEngine`
- `claude_brain.py`: Claude AI decision layer (bypassed when `USE_AI=false`)
- `risk_gate.py`: 6-layer hard checks (confirmation → shorts → shortability → position limits → position size → daily loss)
- `executor.py`: Alpaca order submission with stop-loss and take-profit brackets
- `backtester.py`: Symbol-by-symbol historical replay
- `live_backtest.py`: Portfolio-level bar-by-bar simulation matching live bot behaviour
- `dashboard.py`: Rich terminal dashboard
- `logger.py`: SQLite trade and decision logging
- Grade filter (`MIN_GRADE`) and confirmation quality grading (A/B/C/F) built in from day one

### Config snapshot (defaults at initial commit)

```
WATCHLIST=AAPL,MSFT,NVDA,SPY
MAX_POSITION_SIZE=0.10
MAX_PORTFOLIO_RISK=0.02
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.04
MAX_OPEN_POSITIONS=5
MIN_SIGNALS_REQUIRED=3
MIN_SIGNAL_STRENGTH=0.55
MIN_GRADE=C
ALLOW_SHORTS=true
CONFIRMATION_MODE=strict
MACD_FAST=12
MACD_SLOW=26
MACD_SIGNAL=9
VWAP_MIN_DEVIATION_PCT=0.5
VWAP_SENSITIVITY=3.0
EMA_FAST=50
EMA_SLOW=200
BAR_TIMEFRAME=1Hour
BAR_LIMIT=250
SCAN_INTERVAL_SECONDS=60
```

### Backtest result
> *Not recorded at initial build*
