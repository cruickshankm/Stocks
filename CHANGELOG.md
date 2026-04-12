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

### Backtest after
> *Run `python main.py --live-backtest --start 2026-03-13 --capital 100000` and fill in results*

---

## [Unreleased — 2026-04-12] Pyramid cap + min-grade CLI fix

**Author:** matthew  
**Status:** Uncommitted (working changes)

### Changes

#### risk_gate.py — Pyramid entry cap
- Added `check_pyramid_limit()`: blocks add-ons to an existing position once `MAX_PYRAMID_ENTRIES` is reached
- `run_risk_gate()` now accepts `pyramid_count` parameter (count of entries into this symbol today)
- New check runs as step 4b, between position-limits and position-size checks

#### main.py — Pyramid counter + CLI default fix
- Added `_symbol_entries_today: dict[str, int]` module-level counter, reset each day at midnight
- `scan_symbol()` increments counter on each confirmed fill, passes count to `run_risk_gate()`
- Fixed `--min-grade` CLI flag: was hardcoded to `"C"`, now defaults to `config.MIN_GRADE` (reads from `.env`)

### Config snapshot (active)

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
> *Not yet run — fill in after backtesting*

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
