# Trade Review

> Generated: 2026-03-19 20:25:01 ET  
> Source: `trading_log.db`  
> Total trades in this report: **2**

---

## Summary

| # | Symbol | Dir | Entry (ET) | Shares | Trade Value | Entry Price | Exit Price | P&L | P&L % | Grade | Status |
|---|--------|-----|-----------|--------|-------------|-------------|------------|-----|-------|-------|--------|
| 9 | SPY | SHORT | 2026-03-18 10:11:22 ET | 18 | $12,028.90 | $668.2722 | $659.5800 | $156.46 | +1.30% | C | CLOSED |
| 10 | QQQ | SHORT | 2026-03-18 10:27:03 ET | 21 | $12,583.03 | $599.1919 | $592.7400 | $135.49 | +1.08% | C | CLOSED |

**Total realised P&L (closed trades): +291.95**

---

## Observations & Red Flags

- **Low average confidence: 57.8%** — all trades were marginal signals (Grade B/C). No A-grade setups were taken. Consider adding a minimum confidence threshold (e.g. 0.65) as an additional risk gate.

---

## Individual Trade Detail

### Trade #9 — SPY SHORT [✅ CLOSED]

#### Entry

| Field | Value |
|-------|-------|
| **Date / Time** | 2026-03-18 10:11:22 ET |
| **Symbol** | SPY |
| **Direction** | SHORT |
| **Shares** | 18 |
| **Fill Price** | $668.2722 |
| **Trade Value** | $12,028.90 |
| **Stop Price** | — |
| **Target Price** | — |

#### Exit

| Field | Value |
|-------|-------|
| **Exit Time** | 2026-03-19 15:50:29 ET |
| **Exit Price** | $659.5800 |
| **Time Held** | 29h 39m 7s |
| **P&L ($)** | $156.46 |
| **P&L (%)** | +1.30% |

#### What Triggered This Trade

| Field | Value |
|-------|-------|
| **Signal Grade** | C — Marginal |
| **Confidence** | 60.1% |
| **Confirming** | macd, ema_cross, price_action |
| **Conflicting** | none |
| **Abstaining** | vwap |
| **Weighted Buy Score** | — |
| **Weighted Sell Score** | 1.8035 |
| **Avg Confirming Strength** | 0.6012 |
| **Claude AI Override** | No |
| **Confirmation Mode** | strict |

**Bot Reasoning:**

> USE_AI=false — acting on confirmation engine alone. 3/4 strategies confirm SELL — MACD ✓  VWAP ✗  EMA ✓  PriceAction ✓ — Grade C

#### Strategy Votes

| Strategy | Vote | Strength | Reason |
|----------|------|----------|--------|
| macd | ▼ SELL | 0.5532 | MACD crossed below signal line; histogram=-0.0361 |
| vwap | — ABSTAIN | 0.2000 | Price hugging VWAP (-0.090% deviation) |
| ema_cross | ▼ SELL | 0.7003 | Death cross — EMA9 crossed below EMA21 |
| price_action | ▼ SELL | 0.5500 | Price action bearish: 0.55 sell / 0.00 buy |

---

### Trade #10 — QQQ SHORT [✅ CLOSED]

#### Entry

| Field | Value |
|-------|-------|
| **Date / Time** | 2026-03-18 10:27:03 ET |
| **Symbol** | QQQ |
| **Direction** | SHORT |
| **Shares** | 21 |
| **Fill Price** | $599.1919 |
| **Trade Value** | $12,583.03 |
| **Stop Price** | — |
| **Target Price** | — |

#### Exit

| Field | Value |
|-------|-------|
| **Exit Time** | 2026-03-19 15:50:29 ET |
| **Exit Price** | $592.7400 |
| **Time Held** | 29h 23m 26s |
| **P&L ($)** | $135.49 |
| **P&L (%)** | +1.08% |

#### What Triggered This Trade

| Field | Value |
|-------|-------|
| **Signal Grade** | C — Marginal |
| **Confidence** | 55.5% |
| **Confirming** | macd, vwap, price_action |
| **Conflicting** | none |
| **Abstaining** | ema_cross |
| **Weighted Buy Score** | — |
| **Weighted Sell Score** | 1.6638 |
| **Avg Confirming Strength** | 0.5546 |
| **Claude AI Override** | No |
| **Confirmation Mode** | strict |

**Bot Reasoning:**

> USE_AI=false — acting on confirmation engine alone. 3/4 strategies confirm SELL — MACD ✓  VWAP ✓  EMA ✗  PriceAction ✓ — Grade C

#### Strategy Votes

| Strategy | Vote | Strength | Reason |
|----------|------|----------|--------|
| macd | ▼ SELL | 0.5574 | MACD crossed below signal line; histogram=-0.0741 |
| vwap | ▼ SELL | 0.5564 | Price 0.32% below VWAP with bearish candle |
| ema_cross | — ABSTAIN | 0.4049 | Bearish trend: EMA9(600.65) < EMA21(601.07) |
| price_action | ▼ SELL | 0.5500 | Price action bearish: 0.55 sell / 0.00 buy |

---
