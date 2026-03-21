# AI Trading Bot

An AI-powered algorithmic trading bot using Alpaca for execution and Claude (Anthropic) for decision-making, with a multi-strategy signal confirmation engine.

## Architecture

```
main.py              ← Main loop + CLI flags (--confirm-test, --backtest, --once)
config.py            ← All settings loaded from .env
strategies.py        ← MACD, VWAP, EMA, Price Action + SignalConfirmationEngine
claude_brain.py      ← Claude AI decision engine
risk_gate.py         ← Ordered risk checks (confirmation → shorts → sizing → limits)
executor.py          ← Alpaca order submission (long + short)
logger.py            ← SQLite trade/decision logging + get_confirmation_stats()
dashboard.py         ← Rich terminal dashboard
backtester.py        ← Historical backtesting engine
test_strategies.py   ← Full test suite
```

---

## Setup

### 1. Create and activate a virtual environment

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux / Mac:
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your API keys (the only required fields):

| Variable           | Description                        |
|--------------------|------------------------------------|
| `ALPACA_API_KEY`   | Alpaca API key                     |
| `ALPACA_SECRET_KEY`| Alpaca secret key                  |
| `ALPACA_BASE_URL`  | Paper URL for testing, live for real money |
| `ANTHROPIC_API_KEY`| Anthropic API key for Claude       |

All other settings have sensible defaults and are documented below.

---

## Usage

```bash
# Run the live/paper bot
python main.py

# Dry-run: print confirmation reports for all symbols, no orders placed
python main.py --confirm-test

# Single symbol only
python main.py --symbol AAPL

# One scan cycle then exit
python main.py --once

# Backtest (see Backtesting section below)
python main.py --backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31
```

---

## How a Trade is Triggered

A trade requires **all four layers** to say yes. If any layer fails, the trade is blocked.

```
Layer 1 → Strategies produce signals
Layer 2 → Confirmation engine counts votes
Layer 3 → Claude makes the final decision
Layer 4 → Risk gate does hard checks
              ↓
         Order submitted to Alpaca
         Stop-loss + take-profit set automatically
```

---

### Layer 1 — The Four Strategies

Each strategy analyses the bar data independently and returns a **signal** (`buy`, `sell`, `neutral`) and a **strength score** (0.0 – 1.0).

#### MACD Crossover
Detects momentum shifts using the difference between two EMAs.

| Setting       | Default | Description                                  |
|---------------|---------|----------------------------------------------|
| `MACD_FAST`   | `12`    | Fast EMA period. Lower = reacts faster       |
| `MACD_SLOW`   | `26`    | Slow EMA period                              |
| `MACD_SIGNAL` | `9`     | Signal line smoothing. Lower = more crossovers |

Fires **buy** when the MACD histogram crosses above zero (or is trending positive).  
Fires **sell** when it crosses below zero (or is trending negative).  
Strength grows with the size of the histogram relative to price.

#### VWAP Deviation
Compares current price to the Volume Weighted Average Price.

| Setting                | Default | Description                                               |
|------------------------|---------|-----------------------------------------------------------|
| `VWAP_MIN_DEVIATION_PCT` | `0.5` | Price must be at least this % from VWAP to fire          |
| `VWAP_SENSITIVITY`     | `3.0`  | How quickly strength builds. Lower = fires stronger sooner |

Fires **buy** when price is above VWAP by at least `MIN_DEVIATION_PCT` with a bullish candle.  
Fires **sell** when price is below VWAP by at least `MIN_DEVIATION_PCT` with a bearish candle.

#### EMA Cross (Golden / Death Cross)
Detects long-term trend direction using two EMAs.

| Setting    | Default | Description                                          |
|------------|---------|------------------------------------------------------|
| `EMA_FAST` | `50`    | Fast EMA. Try `20` for more signals, `100` for fewer |
| `EMA_SLOW` | `200`   | Slow EMA. Classic golden cross uses `200`            |

Common alternatives to backtest:

| Pair       | Style                              |
|------------|------------------------------------|
| `20` / `50`  | Short-term — more active, noisier  |
| `50` / `200` | Classic golden/death cross (default) |
| `100` / `200`| Long-term only — very conservative |

Fires **buy** on a golden cross (fast crosses above slow) or while price is above both EMAs in a bullish trend.  
Fires **sell** on a death cross or while price is below both in a bearish trend.

#### Price Action
Pure candlestick analysis — no external indicators.

Scores five components (each adds to a buy or sell score):

| Component               | Max score | Fires when…                                             |
|-------------------------|-----------|---------------------------------------------------------|
| Higher highs / lows     | +0.25     | Last 3 swing highs and lows each exceed the previous   |
| Momentum candle         | +0.20     | Last candle body is >1.5× the 20-bar average body size |
| Support/resistance proximity | +0.20 | Price within 0.5% of 20-bar swing low/high            |
| Closing position        | +0.15     | Last 2 candles close in top/bottom 30% of their range  |
| Consecutive candles     | +0.10     | Last 3 candles are all the same direction              |

Fires **buy** if `buy_score ≥ 0.45` and beats `sell_score`.  
Fires **sell** if `sell_score ≥ 0.45` and beats `buy_score`.

> **Note:** Price action is a supporting signal only. If it is the sole confirming strategy the summary will flag a warning.

---

### Layer 2 — Signal Confirmation Engine

Every scan runs all 4 strategies. Each casts a vote:

| Vote      | Condition                                               |
|-----------|---------------------------------------------------------|
| `buy`     | signal == "buy"  AND strength ≥ `MIN_SIGNAL_STRENGTH`  |
| `sell`    | signal == "sell" AND strength ≥ `MIN_SIGNAL_STRENGTH`  |
| `abstain` | signal == "neutral" OR strength < `MIN_SIGNAL_STRENGTH`|

| Setting                | Default  | Description                                              |
|------------------------|----------|----------------------------------------------------------|
| `MIN_SIGNALS_REQUIRED` | `3`      | Strategies that must agree before a trade (1–4)          |
| `MIN_SIGNAL_STRENGTH`  | `0.55`   | Minimum strength for a vote to count                     |
| `CONFIRMATION_MODE`    | `strict` | `strict` = raw vote count / `weighted` = sum of strengths |

**Strict mode:** needs `MIN_SIGNALS_REQUIRED` votes in the same direction.  
**Weighted mode:** sums strength scores; trade fires if combined score ≥ `MIN_SIGNALS_REQUIRED × 0.6`. Allows two very strong signals to sometimes outweigh a third weak one.

#### Quality grades

| Grade | Condition                                                  |
|-------|------------------------------------------------------------|
| A     | 4/4 agree AND avg confirming strength ≥ 0.75               |
| B     | ≥ 3/4 agree AND avg confirming strength ≥ 0.65             |
| C     | ≥ `MIN_REQUIRED` agree AND avg strength ≥ 0.55 — caution  |
| F     | Not confirmed — no trade                                   |

Claude is instructed to strongly favour Grade A/B, proceed cautiously on Grade C, and default to hold on Grade F unless it has a specific override reason.

---

### Layer 3 — Claude Decision

Controlled by `USE_AI` in `.env`:

```
USE_AI=true    # Claude decides — uses Anthropic API (default)
USE_AI=false   # Confirmation engine decides directly — no API calls, no cost
```

**When `USE_AI=true`:**  
Claude receives the full confirmation report (vote breakdown, grade, strengths, reasons) and returns a structured JSON decision:

- `action` — `buy`, `sell`, or `hold`
- `confidence` — 0.0 to 1.0
- `stop_loss_pct` — suggested stop distance
- `take_profit_pct` — suggested target distance
- `position_size_modifier` — 0.5 to 1.5× (Grade A gets up to 1.2×, overrides get 0.5×)
- `overriding_confirmation` — `true` if Claude is going against the confirmation engine

**When `USE_AI=false`:**  
The confirmed direction is acted on immediately with no AI call. Position size is scaled by grade:

| Grade | Position size |
|-------|---------------|
| A     | 1.0× (full)   |
| B     | 0.9×          |
| C     | 0.75×         |
| F     | hold          |

This mode makes live trading behave identically to the backtester, so backtest results are a closer match to live performance. Useful for running the bot at zero AI cost while you validate the strategy, then switching `USE_AI=true` once you're happy.

> **Note:** The backtester always runs with `USE_AI=false` regardless of this setting — Claude is never called during backtesting.

---

### Layer 4 — Risk Gate

Six hard checks run in order. The first failure blocks the trade immediately:

| Check               | Blocks when…                                                        |
|---------------------|---------------------------------------------------------------------|
| Confirmation gate   | `confirmed == false` (signal not confirmed by enough strategies)    |
| Shorts policy       | `direction == sell` AND `ALLOW_SHORTS=false` in `.env`              |
| Symbol shortable    | Symbol is not shortable / not easy-to-borrow on Alpaca              |
| Position limits     | Already at `MAX_OPEN_POSITIONS`                                     |
| Position size       | Trade value would exceed `MAX_POSITION_SIZE` % of portfolio         |
| Daily loss limit    | Today's realised losses exceed 3% of portfolio                      |

| Setting               | Default | Description                                    |
|-----------------------|---------|------------------------------------------------|
| `MAX_POSITION_SIZE`   | `0.10`  | Max fraction of portfolio per position (10%)   |
| `MAX_OPEN_POSITIONS`  | `5`     | Hard cap on simultaneous open positions        |
| `ALLOW_SHORTS`        | `true`  | Set `false` to disable all short selling       |
| `STOP_LOSS_PCT`       | `0.02`  | Default stop-loss distance from entry (2%)     |
| `TAKE_PROFIT_PCT`     | `0.04`  | Default take-profit distance from entry (4%)   |

---

### Bar data

| Setting        | Default  | Options                              |
|----------------|----------|--------------------------------------|
| `BAR_TIMEFRAME`| `1Hour`  | `1Min`, `5Min`, `15Min`, `1Hour`, `1Day` |
| `BAR_LIMIT`    | `250`    | Number of bars fetched per scan      |

| Timeframe | Bars/day | Best for                          |
|-----------|----------|-----------------------------------|
| `1Min`    | ~390     | Scalping — very noisy             |
| `5Min`    | ~78      | Active intraday                   |
| `15Min`   | ~26      | Intraday swing                    |
| `1Hour`   | ~7       | **Default** — swing/intraday hybrid |
| `1Day`    | 1        | Daily swing — fewest signals      |

---

## Backtesting

Replays historical bars through all four strategies. No real orders are placed.

```bash
# Backtest entire watchlist (last 180 days)
python main.py --backtest

# Single symbol with date range
python main.py --backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31

# Multiple symbols
python main.py --backtest --symbol AAPL,MSFT,GLD --start 2024-01-01

# Test a different timeframe without changing .env
python main.py --backtest --symbol SPY --timeframe 15Min --start 2024-01-01

# Test weighted mode
python main.py --backtest --symbol SPY --mode weighted --start 2024-01-01

# Custom starting capital
python main.py --backtest --symbol NVDA --capital 25000 --start 2024-06-01
```

The report shows: total return, max drawdown, Sharpe ratio, win rate, profit factor, performance broken down by confirmation grade (A/B/C), exit breakdown (targets hit vs stops hit), and a full trade-by-trade table.

---

## Short Selling

Requires an Alpaca **margin account** with shorting enabled.  
Set `ALLOW_SHORTS=true` in `.env`.  
The risk gate verifies each symbol is shortable and easy-to-borrow before submitting.  
Stop-loss for short trades is placed **above** entry; take-profit is placed **below** entry.

---

## Running Tests

```bash
# Using pytest
python -m pytest test_strategies.py -v

# Or directly
python test_strategies.py
```

---

## Dashboard

The live terminal dashboard (powered by Rich) shows:
- Per-symbol confirmation table — vote per strategy, grade, direction, full confluence star ★
- Configuration panel — current settings at a glance
- Historical stats — win rate and avg P&L broken down by confirmation grade (A/B/C/override)
- Status bar — last scan time and trade count
