# Strategy & Config Changelog

All strategy refinements, config changes, and bug fixes are recorded here in reverse chronological order.
Each entry includes a full config snapshot so any version can be exactly reproduced.

---

## ⏭ NEXT SESSION — PICK UP HERE

**Status as of 2026-05-24 session end**

Active config **REVERTED** to `WATCHLIST=UCO,QQQ,IWM,XLE,NVDA` (TQQQ + SOXL removed after disastrous 1-month test below).
`BAR_TIMEFRAME=1Min`, `MIN_GRADE=B`, no timeout.

**🚫 DO NOT RE-TEST:**
- **TQQQ and SOXL on 1Min bars** — total disaster (-2.76% in 1 month, SOXL alone -$2,637 over 29 trades at 17.2% win). 3x-leveraged ETFs are too volatile for a 1Min/2% stop strategy. They get chopped to pieces.

**What to test next (safe ideas only):**
1. **Non-leveraged ETF expansion** — try adding SPY (SPDR S&P 500), DIA (Dow), or XLK (tech sector) instead of leveraged products. These move ~1% per day, similar to current watchlist.
2. **Tighter stop on XLE** — XLE fires 7–15 times per 60-day period at 40–43% win rate. Test global `STOP_LOSS_PCT=0.015` to see the impact (would also affect other symbols).
3. **Capital scaling** — the strategy averages ~$780/week at $100k. To reach the $5k/week goal requires ~$640k capital. If strategy quality is confirmed, scaling capital is the fastest path to the weekly target.

**Current 60-day baseline to beat:** +9.36% return, 22.72 Sharpe, 1.48% max DD, 55.6% win rate (60-day Mar 23–May 22, $100k, 1Min, UCO/QQQ/IWM/XLE/NVDA).

---

## ⏭ NEXT SESSION — PICK UP HERE (previous — 2026-05-23 first session)

**Status as of 2026-05-23 session end**

Active config changed: **WATCHLIST=UCO,QQQ,IWM,XLE,NVDA** (GDX and UNG dropped).
Timeout feature remains disabled (`TRADE_TIMEOUT_BARS=0`).

**What to test next:**
1. **Timeout with relative threshold** — close if progress < 15% of target distance (= 0.9% for 6% target). Requires a small code tweak: `threshold = TAKE_PROFIT_PCT * 0.15`. Both absolute-threshold tests (120/2% and 200/1%) have been worse — this is the remaining idea.
2. **Capital scaling** — the strategy averages ~$780/week at $100k. To reach the $5k/week goal requires ~$640k capital running this config. Consider increasing paper trading capital to $200k to validate.
3. **5-minute bars** — still untested. Would reduce noise on XLE (42.9% win rate). Run `python main.py --live-backtest --start 2026-03-23 --end 2026-05-22 --capital 100000 --timeframe 5Min`.

---

## ⏭ NEXT SESSION — PICK UP HERE (previous — 2026-04-15)

**Status as of 2026-04-15 session end**

The bot is running correctly. No code is broken. `.env` is on the current winning config.

**The one thing left to finish:**
The trade timeout feature was built (code is done, all files updated) but the first parameter test (120 bars / 2% progress) was **too aggressive** — it cut winners short and hurt performance significantly. The feature is currently disabled (`TRADE_TIMEOUT_BARS=0`).

**What to run next — 3 follow-up timeout tests (in order):**

| Test | Command | Rationale |
|------|---------|-----------|
| A — 200 bars / 1% progress | `python main.py --live-backtest --start 2026-02-12 --capital 100000 --timeout-bars 200 --timeout-progress 0.01` | Longer window (3h 20m), softer threshold; Apr 13 GDX reached only 0.93% so 1% still catches it |
| B — 240 bars / 1% progress | `python main.py --live-backtest --start 2026-02-12 --capital 100000 --timeout-bars 240 --timeout-progress 0.01` | Even longer (4 hours) to protect slow-but-real movers |
| C — Relative threshold (15% of target) | Requires a small code tweak — threshold = `TAKE_PROFIT_PCT * 0.15` = 0.9% for 6% target | Ties the exit condition to the actual target distance; most principled approach |

**Once a winning timeout config is found**, set `TRADE_TIMEOUT_BARS` and `TRADE_TIMEOUT_MIN_PROGRESS_PCT` in `.env` and it goes live automatically — no further code changes needed.

**Current baseline to beat:** +14.43% return, 20.98 Sharpe, 1.18% max DD, 55.6% win rate (60-day, $100k, no timeout).

---

## [2026-05-24] FAILED experiment: adding TQQQ + SOXL to watchlist

**Author:** matthew
**Session date:** 2026-05-24
**Test period:** 2026-04-24 to 2026-05-24 (1 month)
**Verdict:** ❌ DISASTER — REVERTED IMMEDIATELY

---

### What happened

After session 3 noted that QQQ/IWM/NVDA had strong win rates when they fired, the suggestion was to add another high-quality ETF to increase trade frequency. TQQQ (3x QQQ) and SOXL (3x semiconductor) were added to the watchlist. The 1-month backtest result:

| Metric | Result |
|--------|--------|
| Total return | **-2.76%** (-$2,756) |
| Sharpe ratio | -5.66 |
| Max drawdown | 3.81% |
| Total trades | 45 (vs ~9 baseline) |
| Win rate | 22.2% |
| Profit factor | 0.73 |

### Per-symbol breakdown

| Symbol | Trades | Win % | P&L | Verdict |
|--------|:-:|:-:|:-:|:-:|
| **SOXL** | **29** | **17.2%** | **-$2,637** | ❌ catastrophic |
| TQQQ | 7 | 28.6% | -$397 | ❌ bad |
| UCO | 2 | 50% | +$572 | ✅ |
| IWM | 1 | 100% | +$294 | ✅ |
| XLE | 4 | 25% | -$4 | ⚠ |
| NVDA | 2 | 0% | -$585 | ❌ |
| QQQ | 0 | — | — | quiet |

### Root cause

**Leveraged ETFs (3x) are fundamentally incompatible with this strategy:**
1. **Volatility kills the 2% stop** — a 0.67% move in QQQ becomes a 2% move in TQQQ, instantly stopping out trades that would have been fine on the underlying.
2. **Signal noise** — 1Min indicators (MACD, EMA, VWAP) generate WAY more signals on 3x ETFs because every wiggle is amplified. SOXL fired 29 times in a month vs ~2 for normal symbols.
3. **Stop-out cascade** — 35 of 45 total trades hit stop-loss. The bot was just feeding the spread.

The original 5 symbols (UCO, QQQ, IWM, XLE, NVDA) actually netted **+$278** over the same period. SOXL + TQQQ alone subtracted $3,034.

### Action taken

- `.env` reverted to `WATCHLIST=UCO,QQQ,IWM,XLE,NVDA` immediately.
- Lesson: **never trade 3x leveraged ETFs on a 1Min strategy with a 2% stop**. They need either a 5% stop or a much higher timeframe (15Min+) to behave.
- Added 🚫 flag in "next session" to prevent re-testing this.

---

### Active config (after revert)

```
WATCHLIST=UCO,QQQ,IWM,XLE,NVDA
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.06
MIN_GRADE=B
BAR_TIMEFRAME=1Min
TRADE_TIMEOUT_BARS=0
```

---

## [2026-05-23] 2-sim follow-up: relative timeout + remove UCO

**Author:** matthew
**Session date:** 2026-05-23
**Review period:** 2026-03-23 to 2026-05-22 (60-day, matches prior baseline)
**Method:** Live-style backtest, $100k capital, 1Min bars

---

### Previous changes checked

Both tests in this session came directly from the "what to test next" list established in the prior session. No duplicates.

---

### Code change — `--timeout-relative` flag

**Files modified:** `live_backtest.py`, `main.py`

Added a `timeout_relative` mode to `_check_exits`. When enabled, the exit threshold is calculated as a fraction of the full target distance rather than an absolute price move:

```
timeout_relative=False (existing): exit if progress < timeout_min_progress_pct (e.g. 2%)
timeout_relative=True  (new):      exit if progress < target_pct × timeout_min_progress_pct
                                   e.g. 6% target × 0.15 factor = 0.9% threshold
```

No `.env` changes. CLI usage: `--timeout-bars N --timeout-progress 0.15 --timeout-relative`

---

### Sim 4 — Relative Timeout (200 bars / 15% of target)

**Rationale:** The last untested timeout variant from the April 15 changelog. Both prior absolute tests (120/2% and 200/1%) were too aggressive and cut winners. The relative version ties the threshold to the actual target distance, making it proportional.

```
python main.py --live-backtest --start 2026-03-23 --end 2026-05-22 --capital 100000 --timeout-bars 200 --timeout-progress 0.15 --timeout-relative
```

| Metric | Baseline (no timeout) | Sim 4 (rel. timeout) | Change |
|--------|:-:|:-:|:-:|
| Total return | +9.36% | +6.43% | -3% worse |
| Sharpe ratio | 22.72 | 15.37 | worse |
| Max drawdown | 1.48% | **0.64%** | **-57% better** |
| Total trades | 18 | 38 | +111% more |
| Win rate | 55.6% | 47.4% | -8pp worse |
| Profit factor | 1.48 | **3.49** | **+2.4x better** |
| Avg win | +$898 | +$500 | smaller wins |
| Avg loss | -$296 | **-$129** | **much smaller losses** |

**Exit breakdown (Sim 4):** 9 target hits, 5 stops, **24 timeouts** (avg timeout P&L: **-$12** — tiny losses)

**Per-symbol (Sim 4):** UCO 50% win (+$3,282), QQQ 0% win (-$82), IWM 60% win (+$1,055), XLE 40% win (+$698), NVDA 57% win (+$1,472)

**Key findings:**
- The relative timeout is fundamentally different from absolute timeouts — instead of cutting winners, it exits tiny-progress trades for very small losses (~$12 average).
- Trade count almost doubles (38 vs 18) because many slow-moving trades that would have eventually stopped out now exit early for minimal damage.
- The dramatic reduction in avg loss (-$296 → -$129) and max drawdown (1.48% → 0.64%) is the standout positive.
- However, return is lower (+6.43% vs +9.36%) because some trades timeout just before hitting their target.
- PF improves significantly (1.48 → 3.49) — the risk/reward profile per trade is much cleaner.
- This timeout makes the strategy more consistent and safer, but at the cost of ~3% total return over 60 days.

**Verdict: NEUTRAL — doesn't beat baseline on return but significantly reduces risk. Consider as a "defensive mode" when market is choppy.**

---

### Sim 5 — Remove UCO (`WATCHLIST=QQQ,IWM,XLE,NVDA`)

**Rationale:** UCO has shown 25% win rate on 5Min (prior session) and varies significantly on 1Min. Testing whether removing it produces cleaner, higher-quality signals on the remaining 4 symbols.

```
python main.py --live-backtest --start 2026-03-23 --end 2026-05-22 --capital 100000
# (with WATCHLIST=QQQ,IWM,XLE,NVDA in .env — restored after)
```

| Metric | Baseline (UCO included) | Sim 5 (no UCO) | Change |
|--------|:-:|:-:|:-:|
| Total return | **+9.36%** | +4.90% | -4.5% worse |
| Sharpe ratio | **22.72** | 19.46 | worse |
| Max drawdown | 1.48% | **0.89%** | better |
| Total trades | **18** | 17 | similar |
| Win rate | **55.6%** | 52.9% | -2.7pp |
| Profit factor | 1.48 | **3.00** | better |
| Avg win | +$898 | +$817 | slightly lower |
| Avg loss | -$296 | -$307 | similar |

**Per-symbol (no UCO):** QQQ 100% win (+$863), IWM 75% win (+$1,669), XLE 42.9% win (+$1,496), NVDA 40% win (+$869)

**Key findings:**
- Removing UCO cuts return from +9.36% → +4.90% — UCO contributed ~$4,500 of the baseline's $9,360 profit. It is a significant positive contributor when conditions are right.
- Without UCO, the remaining 4 symbols show cleaner win rates (QQQ 100%, IWM 75%) and better PF (3.00 vs 1.48).
- The lower Sharpe (19.46 vs 22.72) and lower return confirm UCO is net-positive to the strategy.
- UCO's "bad periods" (high stop rate in April) are more than offset by its target hits in March and May.
- XLE remains the weakest symbol at 42.9% win but is still profitable (+$1,496 over 60 days).

**Verdict: REJECT — UCO adds significant return. Keep UCO in the watchlist. `WATCHLIST` restored to `UCO,QQQ,IWM,XLE,NVDA`.**

---

### Session Summary

| Config | Return | Sharpe | Max DD | Win rate | PF | Verdict |
|--------|:------:|:------:|:------:|:--------:|:--:|---------|
| Baseline (no timeout, UCO in) | **+9.36%** | **22.72** | 1.48% | **55.6%** | 1.48 | — |
| Sim 4 — Relative timeout | +6.43% | 15.37 | **0.64%** | 47.4% | **3.49** | ⚠ Neutral (safer but lower return) |
| Sim 5 — No UCO | +4.90% | 19.46 | 0.89% | 52.9% | 3.00 | ❌ Reject |

**Winner: no change.** The existing config (UCO,QQQ,IWM,XLE,NVDA, 1Min, Grade B, no timeout) remains the best for raw return and Sharpe. The relative timeout is a viable defensive option if drawdown management becomes a priority.

**Notable finding:** UCO is a core contributor (+$4,500 / 60 days). QQQ and IWM are high-quality but low-frequency. XLE is marginal but still profitable. NVDA is volatile but adds meaningful return when signals fire.

---

### Active config (unchanged)

```
WATCHLIST=UCO,QQQ,IWM,XLE,NVDA
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.06
MIN_GRADE=B
MIN_SIGNAL_STRENGTH=0.55
MIN_SIGNALS_REQUIRED=3
CONFIRMATION_MODE=strict
TREND_FILTER_ENABLED=false
ALLOW_SHORTS=true
TRADE_TIMEOUT_BARS=0
BAR_TIMEFRAME=1Min
BAR_LIMIT=500
MAX_OPEN_POSITIONS=6
MAX_POSITION_SIZE=0.166
```

---

## [2026-05-23] 1-month baseline + 3-sim optimisation session (5Min bars, longs-only, Grade C)

**Author:** matthew
**Session date:** 2026-05-23
**Review period:** 2026-04-23 to 2026-05-22 (1 calendar month)
**Method:** Live-style backtest, $100k capital, UCO/QQQ/IWM/XLE/NVDA watchlist

---

### Previous changes checked

| Area | Status |
|------|--------|
| Take-profit: 4%/5%/6%/7% | Tested — 6% wins |
| Stop-loss: 2% vs 1.5% | Tested — 2% wins |
| Signal strength: 0.55 vs 0.65 | Tested — 0.55 wins |
| VWAP 0.15/1.5 vs 0.25/2.0 | Tested — 0.15/1.5 wins |
| Trend filter ON/OFF | Tested — OFF wins |
| Weighted vs strict confirmation | Tested — no difference |
| Trade timeout (120/2%, 200/1%) | Tested — both worse |
| Watchlist trimming (multiple rounds) | Done — active: UCO,QQQ,IWM,XLE,NVDA |
| MIN_GRADE B vs C | Tested on OLD watchlist only — re-tested here on new watchlist |
| BAR_TIMEFRAME 5Min | **Untested — tested this session** |
| ALLOW_SHORTS on/off | **Untested — tested this session** |

---

### 1-Month Baseline (Apr 23 – May 22, 1Min bars, MIN_GRADE=B)

```
python main.py --live-backtest --start 2026-04-23 --end 2026-05-22 --capital 100000
```

| Metric | Result |
|--------|--------|
| Total return | +0.16% (+$158) |
| Sharpe ratio | 1.16 |
| Max drawdown | 1.19% |
| Total trades | 9 |
| Win rate | 33.3% |
| Profit factor | 1.09 |
| Avg win | +$647 |
| Avg loss | -$297 |

**Per-symbol:** UCO 50% win (+$597), QQQ 0 trades, IWM 100% win (+$160), XLE 25% win (-$4), NVDA 0% win (-$594)

**Assessment:** Very low activity in the last month. NVDA dragging (0% win, -$594). XLE losing overall. Only 9 trades in 22 trading days (0.41/day). The recent market environment appears choppy on 1-minute resolution.

---

### Sim 1 — 5-Minute Bars (`--timeframe 5Min`)

**Change:** `BAR_TIMEFRAME: 1Min → 5Min` (CLI override only, .env not modified)
**Rationale:** On the "what to test next" list. Reduces intraday noise — 5-minute bars filter out micro-fluctuations that generate false 1Min signals.

```
python main.py --live-backtest --start 2026-04-23 --end 2026-05-22 --capital 100000 --timeframe 5Min
```

| Metric | Baseline (1Min) | Sim 1 (5Min) | Change |
|--------|:-:|:-:|:-:|
| Total return | +0.16% | **+1.49%** | **+9.3x** |
| Sharpe ratio | 1.16 | **20.24** | **+17.5x** |
| Max drawdown | 1.19% | **0.60%** | **-50%** |
| Total trades | 9 | 5 | -44% |
| Win rate | 33.3% | **60.0%** | **+26.7pp** |
| Profit factor | 1.09 | **3.51** | **+3.2x** |
| Avg win | +$647 | +$697 | +8% |
| Avg loss | -$297 | -$298 | flat |

**Per-symbol (5Min):** UCO 33.3% win (+$294), QQQ 0 trades, IWM 0 trades, XLE 0 trades, NVDA **100% win (+$1,200)**

**Key findings:**
- Fewer trades (5 vs 9) but dramatically higher quality — win rate nearly doubled.
- NVDA flips from 0% → 100% win rate. The 1Min noise on NVDA was generating bad signals; 5Min filters them out.
- XLE drops to zero trades (it was 25% win on 1Min), which is exactly what we want — fewer bad trades.
- Sharpe of 20.24 is exceptional (consistent daily gains with almost no drawdown).
- The 5-minute signal is arriving at cleaner confirmation points.

**Verdict: STRONG POSITIVE — best result of the session. Needs 60-day validation before activating.**

---

### Sim 2 — Long-Only (`ALLOW_SHORTS=false`)

**Change:** `ALLOW_SHORTS: true → false` (temporarily modified in .env, then restored)
**Rationale:** Completely untested. Hypothesis: if short signals are low quality in current conditions (post-tariff uncertainty), filtering them would improve results.

```
python main.py --live-backtest --start 2026-04-23 --end 2026-05-22 --capital 100000
# (with ALLOW_SHORTS=false in .env)
```

| Metric | Baseline (1Min) | Sim 2 (Longs only) | Change |
|--------|:-:|:-:|:-:|
| Total return | +0.16% | -0.44% | **WORSE** |
| Sharpe ratio | 1.16 | -5.79 | **WORSE** |
| Max drawdown | 1.19% | 0.89% | slightly better |
| Total trades | 9 | 7 | -22% |
| Win rate | 33.3% | 28.6% | -4.7pp worse |
| Profit factor | 1.09 | 0.70 | **WORSE** |

**Key findings:**
- Long-only is clearly worse — removing shorts cost us the UCO short that hit its 6% profit target (UCO fell from $50 → $47, a profitable short).
- The two dropped trades (1 UCO short, 1 XLE short) included one winner; removing them pushed the portfolio negative.
- Current market has been moving in both directions. Our short signals are not the problem — the issue is 1Min noise on entries.

**Verdict: REJECT — shorts add value. Keep `ALLOW_SHORTS=true`.**

---

### Sim 3 — Grade C Signals (`MIN_GRADE=C`)

**Change:** `MIN_GRADE: B → C` (temporarily modified in .env, then restored)
**Rationale:** Grade B was chosen on the old 11-symbol watchlist. Never re-tested on the current 5-symbol watchlist. Grade C allows trades with 3/4 strategies confirming at ≥0.55 strength (vs Grade B: 3/4 + avg strength ≥0.65).

```
python main.py --live-backtest --start 2026-04-23 --end 2026-05-22 --capital 100000
# (with MIN_GRADE=C in .env)
```

| Metric | Baseline (1Min) | Sim 3 (Grade C) | Change |
|--------|:-:|:-:|:-:|
| Total return | +0.16% | +0.59% | +3.7x |
| Sharpe ratio | 1.16 | 2.10 | +1.8x |
| Max drawdown | 1.19% | 1.61% | +35% worse |
| Total trades | 9 | 27 | +3x |
| Win rate | 33.3% | 29.6% | -3.7pp worse |
| Profit factor | 1.09 | 1.13 | marginal |

**Grade breakdown (Sim 3):** Grade B: 4 trades, 25% win, -$5 | Grade C: 23 trades, 30.4% win, +$596

**Key findings:**
- Lowering to Grade C triples trade frequency, which is appealing, but win rate drops.
- The 23 extra Grade C trades generated 7 wins / 16 losses — not a reliable edge.
- The higher drawdown (1.61% vs 1.19%) is a concern.
- QQQ finally trades (+$1,047 from 2 Grade C wins) — interesting, but sample is tiny.
- While total return improves 3.7x (noise, low absolute value), quality metrics deteriorate.
- Combining Grade C + 5Min bars might be interesting — 5Min would filter the noisy Grade C entries. Not tested yet.

**Verdict: NEUTRAL/SLIGHT NEGATIVE — more trades but lower quality. Hold at MIN_GRADE=B for now.**

---

### Session Summary

| Config | Return | Sharpe | Max DD | Win rate | PF | Verdict |
|--------|:------:|:------:|:------:|:--------:|:--:|---------|
| Baseline (1Min, Grade B) | +0.16% | 1.16 | 1.19% | 33.3% | 1.09 | — |
| Sim 1 — 5Min bars | **+1.49%** | **20.24** | **0.60%** | **60.0%** | **3.51** | ✅ Strong positive |
| Sim 2 — Longs only | -0.44% | -5.79 | 0.89% | 28.6% | 0.70 | ❌ Reject |
| Sim 3 — Grade C | +0.59% | 2.10 | 1.61% | 29.6% | 1.13 | ⚠ Neutral |

**Winner: 5-minute bars.** The 1Min timeframe is generating too much noise on this watchlist in the current market environment. Switching to 5Min dramatically improves signal quality across all metrics.

**Winner of this session: 5-minute bars** over the 1-month window. But 60-day validation (below) overturned this — **final verdict: keep 1Min.**

---

### 60-Day Validation — 5-Minute Bars (Mar 23 – May 22)

After the 1-month sim showed 5Min dramatically outperforming, this validation run covers the full 60-day period used as the strategy benchmark.

```
python main.py --live-backtest --start 2026-03-23 --end 2026-05-22 --capital 100000 --timeframe 5Min
```

| Metric | 60-day Baseline (1Min) | 60-day Validation (5Min) | Verdict |
|--------|:-:|:-:|:-:|
| Total return | **+9.36%** | +1.18% | ❌ Worse |
| Sharpe ratio | **22.72** | 6.08 | ❌ Worse |
| Max drawdown | **1.48%** | 2.36% | ❌ Worse |
| Total trades | **18** | 14 | fewer |
| Win rate | **55.6%** | 35.7% | ❌ Worse |
| Profit factor | **1.48** | 1.44 | flat |

**Per-symbol (5Min, 60-day):** UCO 12 trades 25% win (-$16), NVDA 2 trades 100% win (+$1,200), QQQ/IWM/XLE 0 trades.

**Key findings:**
- 5Min was good in the most recent month (Apr 23–May 22: +1.49%) but bad in the prior month (Mar 23–Apr 22).
- UCO is the culprit: 12 trades over 60 days at 25% win rate on 5Min bars. The 5Min bar rhythm does not suit UCO's volatile, whipsaw price action. On 1Min bars, the strategy caught UCO's bigger intraday moves earlier; on 5Min it fires later and gets stopped out more.
- NVDA on 5Min is excellent (100% win, +$1,200) but sample size is only 2 trades.
- The 1-month win for 5Min appears to be period-specific, not a structural improvement.

**Verdict: REJECT — 5Min does not beat the 60-day 1Min baseline. Keep `BAR_TIMEFRAME=1Min`.**

---

### Active config (unchanged)

```
WATCHLIST=UCO,QQQ,IWM,XLE,NVDA
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.06
MIN_GRADE=B
MIN_SIGNAL_STRENGTH=0.55
MIN_SIGNALS_REQUIRED=3
CONFIRMATION_MODE=strict
TREND_FILTER_ENABLED=false
ALLOW_SHORTS=true
TRADE_TIMEOUT_BARS=0
BAR_TIMEFRAME=1Min
BAR_LIMIT=500
MAX_OPEN_POSITIONS=6
MAX_POSITION_SIZE=0.166
```

---

## [2026-05-23] Weekly review + watchlist overhaul (drop GDX & UNG, add NVDA)

**Author:** matthew
**Session date:** 2026-05-23
**Review period:** Week of 2026-05-18 to 2026-05-22
**Method:** Signal analysis (analyse_day.py) + 60-day live-style backtest (Mar 23 – May 22, $100k)

---

### Weekly trade review

**Bot status: NOT RUNNING this week — 0 trades executed.**
Alpaca confirmed 0 filled orders Mon–Fri. The bot was not active during the trading week.

**Signals that fired (what was missed):**

| Day | Symbol | Dir | Time ET | Price | Grade |
|-----|--------|-----|---------|-------|-------|
| Mon May 18 | XLE | BUY | 11:07 | $60.24 | B |
| Tue May 19 | XLE | BUY | 14:04 | $61.14 | B |
| Wed May 20 | UCO | SELL | 10:14 | $50.51 | B |
| Wed May 20 | IWM | BUY | 11:15 | $279.45 | B |
| Wed May 20 | XLE | SELL | 12:34 | $60.27 | B |
| Wed May 20 | GDX | BUY | 15:00 | $86.55 | B |
| Thu May 21 | UNG | SELL | 10:30 | $11.35 | B |
| Thu May 21 | GDX | BUY | 14:24 | $87.20 | B |
| Fri May 22 | GDX | BUY | 12:58 | $85.64 | B |

**What the bot would have made (week simulation):**

`python main.py --live-backtest --start 2026-05-18 --end 2026-05-23 --capital 100000`

| Metric | Value |
|--------|-------|
| Total return | -0.09% |
| Total P&L | **$-94.19** |
| Trades | 7 |
| Win rate | 28.6% |
| Targets hit | 1 (UCO SELL → +$896) |
| Stops hit | 4 (GDX ×2, XLE, UNG) |

**Key observation:** Even if the bot had been running, this would have been a losing week. Not because of strategy failure — but because **GDX went 0/3 with all stops** and UNG 0/1. The $5k weekly target is not achievable on a week like this at $100k capital. The real goal should be ~$780/week average at $100k (see capital analysis below).

---

### Strategy health check — recent 60-day baseline (Mar 23 – May 22)

`python main.py --live-backtest --start 2026-03-23 --end 2026-05-22 --capital 100000`

| Metric | Feb–Apr baseline | Mar–May recent | Change |
|--------|-----------------|----------------|--------|
| Total return | +14.43% | **+8.81%** | -5.6pp |
| Sharpe ratio | 20.98 | **17.55** | worse |
| Max drawdown | 1.18% | **1.78%** | worse |
| Trades | 45 | **33** | fewer |
| Win rate | 55.6% | **48.5%** | -7.1pp |
| Profit factor | 3.35 | **2.65** | worse |

**Performance has degraded since April.** The recent 60-day period is weaker across all metrics. Per-symbol breakdown tells the story clearly:

| Symbol | Trades | Win% | P&L | Verdict |
|--------|--------|------|-----|---------|
| UCO | 10 | 60.0% | +$4,306 | Strong |
| IWM | 4 | 75.0% | +$1,752 | Strong |
| QQQ | 1 | 100% | +$897 | Strong |
| XLE | 7 | 42.9% | +$1,572 | Marginal |
| **GDX** | **9** | **33.3%** | **+$939** | **Marginal** |
| **UNG** | **2** | **0.0%** | **-$651** | **Avoid** |

**GDX and UNG are the clear weak links.** GDX's 33.3% win rate means it loses more often than it wins — it's dragging quality metrics down even when net P&L is marginally positive. UNG is 0/2, pure loss.

---

### Simulation results

All sims run on Mar 23 – May 22 window, $100k capital, same base config.

| # | Config | Return | Sharpe | Max DD | Trades | Win% | PF |
|---|--------|--------|--------|--------|--------|------|----|
| Baseline | GDX,UCO,QQQ,IWM,XLE,UNG | +8.81% | 17.55 | 1.78% | 33 | 48.5% | 2.65 |
| **1** | **UCO,QQQ,IWM,XLE (drop GDX+UNG)** | **+8.45%** | **25.31** | **1.19%** | **22** | **59.1%** | **3.99** |
| 2 | Timeout 200 bars / 1% (all 6) | +3.43% | 7.28 | 1.73% | 45 | 40.0% | 1.74 |
| **3 🏆** | **UCO,QQQ,IWM,XLE,NVDA (drop GDX+UNG, add NVDA)** | **+9.36%** | **22.72** | **1.48%** | **27** | **55.6%** | **3.46** |

**Sim 1 — Drop GDX + UNG (4 symbols):** Almost identical return to baseline but massive quality improvement: Sharpe 25.31 (vs 17.55), win rate 59.1% (vs 48.5%), max DD 1.19% (vs 1.78%), profit factor 3.99 (vs 2.65). The two removed symbols were pure drag.

**Sim 2 — Timeout 200 bars / 1% (second test from April backlog):** Still worse. 26 of 45 trades timed out at average -$20, cutting positions before they developed. Return halved to +3.43%. The absolute-threshold timeout concept is definitively not working — any timeout needs a relative threshold tied to the target distance. Marking this timeout approach as closed; only the relative threshold variant (15% of take-profit) is worth attempting.

**Sim 3 🏆 — UCO,QQQ,IWM,XLE,NVDA:** Best return at +9.36%, Sharpe 22.72, win rate 55.6%, PF 3.46. NVDA contributed +$905 over 5 trades (40% win rate — marginal but positive). Better than baseline on all metrics. This is the new active config.

---

### Capital analysis — why $5k/week is hard at $100k

Sim 3 (best config) over 60 days = **$9,360 total** = **$156/day average** = **$780/week average**.

To generate $5k/week:
- At current daily average: need **~$640k capital** ($5,000 / $156 × $100k)
- Or accept weeks where the strategy lands 5–6 target hits (theoretically ~$4,500–$5,500 at current trade sizing)

The strategy is sound and consistent — it's a capital scaling problem, not a strategy problem. The bot running on $100k paper realistically targets $500–$1,500/week depending on market conditions, with occasional exceptional weeks of $2,500+. Getting to $5k requires either more capital or accepting higher position sizing risk.

---

### Decisions

- **GDX removed from watchlist** — consistently underperforming in recent months (33.3% recent win rate, 0/3 this week). May have been a volatility-regime play in Feb-Apr tariff period; no longer warranted.
- **UNG removed from watchlist** — 0% win rate in recent 60-day period, -$651.
- **NVDA added** — 5 trades, 40% win rate, net +$905 in recent period. Adds tech-sector diversity. Previously flagged as "monitor for 2 weeks" (April 14 session); 5+ weeks have now passed, adopting permanently.
- **Timeout (absolute threshold) — closed** — both 120/2% and 200/1% tests were clearly worse. Only the relative threshold variant (close if <15% of target distance after 200 bars) is worth testing, which requires a code change.

---

### Active config (CHANGED)

```
WATCHLIST=UCO,QQQ,IWM,XLE,NVDA       ← changed (dropped GDX, UNG; added NVDA)
MAX_POSITION_SIZE=0.166
MAX_PORTFOLIO_RISK=0.07
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.06
MAX_OPEN_POSITIONS=6
MAX_PYRAMID_ENTRIES=1
MIN_SIGNALS_REQUIRED=3
MIN_SIGNAL_STRENGTH=0.55
MIN_GRADE=B
ALLOW_SHORTS=true
CONFIRMATION_MODE=strict
MACD_FAST=5 / MACD_SLOW=13 / MACD_SIGNAL=6
VWAP_MIN_DEVIATION_PCT=0.15 / VWAP_SENSITIVITY=1.5
EMA_FAST=9 / EMA_SLOW=21
TREND_FILTER_ENABLED=false
TRADE_TIMEOUT_BARS=0
BAR_TIMEFRAME=1Min / BAR_LIMIT=500
```

---

## [2026-04-15] EOD trade timeout — build + 60-day backtest

**Author:** matthew
**Session date:** 2026-04-15
**Method:** 63-day live-style backtest (2026-02-12 to 2026-04-15, $100k starting capital, 1Min bars)
**Command:** `python main.py --live-backtest --start 2026-02-12 --capital 100000 --timeout-bars 120 --timeout-progress 0.02`

---

### What was built

Added a trade timeout mechanism across the full stack:

#### config.py
- `TRADE_TIMEOUT_BARS` — bars a position must be open before timeout is checked (default `0` = disabled)
- `TRADE_TIMEOUT_MIN_PROGRESS_PCT` — minimum move toward target required to avoid timeout (default `0.02` = 2%)

#### live_backtest.py
- `_check_exits()` — extended with `timeout_bars` / `timeout_min_progress_pct` params; timeout fires after stop/target checks, closes at bar close at the `"timeout"` exit reason
- `run_live_backtest()` — accepts `timeout_bars` / `timeout_min_progress_pct` params (falls back to config); displays timeout settings in the header
- `print_live_backtest_report()` — "Timeout" row added to exit breakdown table

#### main.py
- `--timeout-bars N` and `--timeout-progress PCT` CLI flags pass through to `run_live_backtest()`
- `_check_position_timeouts(trading_client)` — live bot function; queries open DB trades, computes bars held from entry timestamp, checks progress vs current Alpaca price, closes and marks DB record if timeout conditions met
- Called at the top of each `run_once()` scan cycle (runs silently if `TRADE_TIMEOUT_BARS=0`)

#### logger.py
- `get_open_trades()` — returns all unclosed trade records for the live bot timeout check

---

### Motivation

April 13 live session: GDX LONG entered at $98.02, held 3h 43m (~224 bars), exited at EOD +0.93% ($+134.68). The 6% target ($103.90) was never approached. A timeout rule should close slow-moving positions and free capital for better setups.

---

### Test result — 120 bars / 2% progress threshold

| Metric | Baseline (no timeout) | Timeout 120 bars / 2% | Change |
|---|---|---|---|
| Total return | +14.43% | **+5.03%** | -9.4pp |
| Sharpe ratio | 20.98 | **8.92** | -12.06 |
| Max drawdown | 1.18% | **1.92%** | worse |
| Total trades | 45 | **61** | +16 |
| Win rate | 55.6% | **47.5%** | -8.1pp |
| Profit factor | 3.35 | **2.03** | -1.32 |
| Avg win | $+880 | **$+342** | much lower |
| Avg loss | $-300 | **$-153** | lower |

**Exit breakdown:**

| Exit | Count | Avg P&L |
|---|---|---|
| Target hit | 8 | $+905 |
| Stop hit | 11 | $-301 |
| Timeout | **42** | **$+26** |

---

### Verdict: PARAMETERS TOO AGGRESSIVE — do not activate

The timeout fired on 42 of 61 trades, averaging only +$26 each. In the baseline (no timeout), many of those same positions went on to hit the 6% target (~$880 avg). The 2-hour / 2% threshold is cutting winners off mid-run — our symbols sometimes take 3–4 hours to develop a 6% move.

The timeout concept is sound (the Apr 13 GDX trade is exactly what it's designed to catch), but the parameters need to be much more lenient for a 6% target. `TRADE_TIMEOUT_BARS` remains `0` (disabled) in `.env`.

---

### What to test next for the timeout

1. **Longer window** — try 200 bars (3h 20m) instead of 120; gives slow-developing moves more time
2. **Lower progress threshold** — try 0.01 (1%) instead of 0.02 (2%); the GDX Apr 13 trade only reached 0.93% so even 1% would have caught it
3. **Relative threshold** — close if progress < 15% of the target distance (for 6% target = 0.9% absolute); ties the threshold to the actual target rather than a fixed %
4. **Symbol-specific** — GDX had 21 trades this period, many timed out; UCO (55.6% win rate) should probably be exempt

---

### Active config (unchanged)

```
WATCHLIST=GDX,UCO,QQQ,IWM,XLE,UNG
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.06
MIN_GRADE=B
MIN_SIGNAL_STRENGTH=0.55
MIN_SIGNALS_REQUIRED=3
CONFIRMATION_MODE=strict
TREND_FILTER_ENABLED=false
TRADE_TIMEOUT_BARS=0              ← new setting, disabled
TRADE_TIMEOUT_MIN_PROGRESS_PCT=0.02  ← new setting (used when bars > 0)
MACD_FAST=5 / MACD_SLOW=13 / MACD_SIGNAL=6
VWAP_MIN_DEVIATION_PCT=0.15 / VWAP_SENSITIVITY=1.5
EMA_FAST=9 / EMA_SLOW=21
BAR_TIMEFRAME=1Min / BAR_LIMIT=500
MAX_OPEN_POSITIONS=6 / MAX_POSITION_SIZE=0.166
```

---

## [2026-04-15] 3-simulation optimisation session

**Author:** matthew
**Session date:** 2026-04-15
**Method:** 62-day live-style backtest (2026-02-12 to 2026-04-14, $100k starting capital, 1Min bars)
**Base command:** `python main.py --live-backtest --start 2026-02-12 --capital 100000`

---

### Session context — live trade review (Apr 13 & 14)

**April 13 (from TRADE_REVIEW.md):**
1 trade executed — GDX LONG @ $98.02, held 3h 43m, exited at EOD @ $98.93 (+$134.68 / +0.93%).
The 6% target ($103.90) was never reached — the position was liquidated by the EOD routine at 15:51 ET.
Only 1 signal fired all day, suggesting the market was slow/choppy for the watchlist.

**April 14:**
No live trade data available (was an optimisation session — bot not running).

**Key observation:** the Apr 13 GDX trade illustrates an important pattern — a position can sit open all day without approaching its target and exit at a small gain. Trade frequency is currently ~0.75/day across 6 symbols. This is low and worth monitoring.

---

### What we checked before running tests

Reviewed CHANGELOG to avoid retesting covered ground:
- Take-profit 4% / 5% / 6% — all done (6% is the winner)
- Stop-loss 2% vs 1.5% — done (2% wins)
- Signal strength 0.55 vs 0.65 — done (0.65 was catastrophic)
- VWAP 0.15/1.5 vs 0.25/2.0 — done (0.15/1.5 wins)
- Trend filter ON/OFF — done multiple times (OFF wins for volatile conditions)
- Watchlist trim (removing USO, GDXJ, SLV, TLT, SPY) — done

**Untested areas addressed this session:**
1. 7% take-profit (directly suggested in Apr 14 "what to test next")
2. Adding NVDA to the trimmed watchlist (suggested in Apr 14 "what to test next")
3. Weighted confirmation mode (never tested — only "strict" used in all previous sessions)

---

### Full test results

| # | What changed vs baseline | Return | Sharpe | Max DD | Trades | Win% | PF |
|---|---|---|---|---|---|---|---|
| Baseline | 6% target, strict, watchlist=6 | +14.43% | 20.98 | 1.18% | 45 | 55.6% | 3.35 |
| **1** | **+ 7% take-profit** | **+7.59%** | **11.18** | **2.94%** | **42** | **38.1%** | **1.98** |
| **2 🏆** | **+ NVDA added to watchlist** | **+16.03%** | **19.97** | **1.18%** | **52** | **51.9%** | **3.07** |
| **3** | **+ Weighted confirmation mode** | **+14.66%** | **21.20** | **1.18%** | **45** | **53.3%** | **3.26** |

> Baseline figures are from the Apr 14 session (Feb 12 – Apr 13 window). Tests 1–3 ran Feb 12 – Apr 14 (one extra day), so direct comparison is approximate but materially accurate.

---

### Key findings

**1. 7% take-profit — REJECTED**
Win rate collapsed from 55.6% → 38.1%. Targets hit: 14 out of 42 vs 24/45 at 6%. The 4%→5%→6% improvement trend does NOT continue to 7%. Moves large enough to reach 6% frequently reverse before hitting 7% on our volatile symbols. Max drawdown doubled to 2.94% as more positions were stopped out on reversal. 6% remains the optimal take-profit.

**2. Adding NVDA to watchlist — CONDITIONAL POSITIVE**
Best total return at +16.03% (+1.6pp over baseline), max drawdown unchanged at 1.18%. NVDA contributed +$1,276 net P&L across 7 trades (42.9% win rate), positive despite below-average win rate because the avg win (~$837) is 2.7× the avg loss (~$309). The downside: overall win rate diluted from 55.6% → 51.9% and profit factor dropped 3.35 → 3.07. NVDA's 42.9% win rate over this period makes it "Marginal" — needs live monitoring before making it permanent.

**3. Weighted confirmation mode — NEUTRAL / SLIGHT POSITIVE**
Virtually identical to strict mode: same 45 trades, +14.66% vs +14.43%, same 1.18% drawdown. Sharpe marginally improved (21.20 vs 20.98). Weighted mode doesn't meaningfully change which entries are taken on this watchlist — the VWAP and EMA signals at 0.55 strength don't often combine to unlock trades that strict mode misses. No reason to change.

---

### Decisions

- **7% take-profit**: Do not adopt. 6% remains optimal.
- **NVDA on watchlist**: Hold — do not add yet. Monitor live behaviour over 2 weeks before committing. If NVDA maintains ≥50% win rate in live sessions, add to `.env`.
- **Weighted mode**: No change. Strict mode stays.

---

### What to test next (updated)

1. **Monitor NVDA live** — run bot with WATCHLIST including NVDA for 2 weeks, track win rate. If ≥50%, adopt permanently.
2. **5-minute bars** — current 1Min is very noisy (38.1% win rate for some symbols at 7% target shows sensitivity). 5Min bars may reduce noise and improve signal quality without losing much frequency.
3. **Tiered position sizing** — currently Grade A gets 1.0 modifier, B gets 0.9. Testing with A=1.15 / B=0.90 / C=0.70 to amplify higher-confidence entries.
4. **EOD trade timeout** — Apr 13 GDX sat open 3h 43m without approaching target (+0.93% at EOD). A rule to close positions that haven't moved ≥2% toward target after 120 bars (~2 hours) could free capital for better setups.

---

### Active config (unchanged — baseline config still wins)

```
WATCHLIST=GDX,UCO,QQQ,IWM,XLE,UNG
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.06
MIN_GRADE=B
MIN_SIGNAL_STRENGTH=0.55
MIN_SIGNALS_REQUIRED=3
CONFIRMATION_MODE=strict
TREND_FILTER_ENABLED=false
MACD_FAST=5 / MACD_SLOW=13 / MACD_SIGNAL=6
VWAP_MIN_DEVIATION_PCT=0.15 / VWAP_SENSITIVITY=1.5
EMA_FAST=9 / EMA_SLOW=21
BAR_TIMEFRAME=1Min / BAR_LIMIT=500
MAX_OPEN_POSITIONS=6 / MAX_POSITION_SIZE=0.166
```

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
