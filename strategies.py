"""
Trading strategies and signal confirmation engine.

Strategies:
  1. MACD crossover
  2. VWAP deviation
  3. EMA 50/200 cross
  4. Price Action (candlestick structure + momentum)

Each strategy returns a signal dict:
  {"signal": "buy" | "sell" | "neutral", "strength": float, "reason": str, ...}

The SignalConfirmationEngine / evaluate_confirmation() aggregates all four.
"""

from __future__ import annotations

import logging
from statistics import mean
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import config

_ET = ZoneInfo("America/New_York")

logger = logging.getLogger(__name__)

SignalValue = Literal["buy", "sell", "neutral"]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _ema_series(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


# ─── Trend pre-filter ─────────────────────────────────────────────────────────

def get_trend_direction(bars: pd.DataFrame, period: int = 200) -> str:
    """
    Macro trend direction based on a long-period EMA.

    Returns:
        'bull'    → price is above the EMA  (favour longs, block shorts)
        'bear'    → price is below the EMA  (favour shorts, block longs)
        'neutral' → not enough bars to compute EMA reliably

    Using 200 × 1Min bars ≈ 3.3 hours of intraday context — enough to know
    whether the session trend is up or down without requiring daily data.
    """
    if len(bars) < period + 1:
        return "neutral"
    ema = _ema_series(bars["close"], period)
    close = float(bars["close"].iloc[-1])
    ema_val = float(ema.iloc[-1])
    if close > ema_val:
        return "bull"
    elif close < ema_val:
        return "bear"
    return "neutral"


# ─── Strategy 1: MACD Crossover ───────────────────────────────────────────────

def get_macd_signal(
    df: pd.DataFrame,
    fast: int = None,
    slow: int = None,
    signal: int = None,
) -> dict:
    """
    MACD crossover signal.
    Periods default to MACD_FAST / MACD_SLOW / MACD_SIGNAL from .env (12/26/9).
    """
    _fast   = fast   if fast   is not None else config.MACD_FAST
    _slow   = slow   if slow   is not None else config.MACD_SLOW
    _signal = signal if signal is not None else config.MACD_SIGNAL

    min_bars = _slow + _signal + 2
    if len(df) < min_bars:
        return {"signal": "neutral", "strength": 0.0,
                "reason": f"insufficient data for MACD (have {len(df)}, need {min_bars})"}

    close = df["close"]
    ema12 = _ema_series(close, _fast)
    ema26 = _ema_series(close, _slow)
    macd_line = ema12 - ema26
    signal_line = _ema_series(macd_line, _signal)
    histogram = macd_line - signal_line

    current_hist = histogram.iloc[-1]
    prev_hist = histogram.iloc[-2]
    current_macd = macd_line.iloc[-1]
    current_price = close.iloc[-1]

    crossover_up = prev_hist < 0 and current_hist > 0
    crossover_down = prev_hist > 0 and current_hist < 0
    trending_up = current_hist > 0 and current_macd > 0
    trending_down = current_hist < 0 and current_macd < 0

    hist_magnitude = abs(current_hist) / (current_price * 0.01)
    raw_strength = _clamp(hist_magnitude * 2)

    if crossover_up:
        strength = _clamp(0.55 + raw_strength * 0.3)
        signal: SignalValue = "buy"
        reason = f"MACD crossed above signal line; histogram={current_hist:.4f}"
    elif trending_up:
        strength = _clamp(0.40 + raw_strength * 0.25)
        signal = "buy" if strength >= 0.5 else "neutral"
        reason = f"MACD and histogram positive; histogram={current_hist:.4f}"
    elif crossover_down:
        strength = _clamp(0.55 + raw_strength * 0.3)
        signal = "sell"
        reason = f"MACD crossed below signal line; histogram={current_hist:.4f}"
    elif trending_down:
        strength = _clamp(0.40 + raw_strength * 0.25)
        signal = "sell" if strength >= 0.5 else "neutral"
        reason = f"MACD and histogram negative; histogram={current_hist:.4f}"
    else:
        strength = raw_strength * 0.3
        signal = "neutral"
        reason = f"No clear MACD crossover; histogram={current_hist:.4f}"

    return {
        "signal": signal,
        "strength": round(strength, 4),
        "reason": reason,
        "macd": round(float(current_macd), 6),
        "signal_line": round(float(signal_line.iloc[-1]), 6),
        "histogram": round(float(current_hist), 6),
        "params": {"fast": _fast, "slow": _slow, "signal": _signal},
    }


# ─── Strategy 2: VWAP Deviation ───────────────────────────────────────────────

def get_vwap_signal(
    df: pd.DataFrame,
    min_deviation_pct: float = None,
    sensitivity: float = None,
) -> dict:
    """
    VWAP signal based on price position relative to intraday VWAP.

    VWAP is computed only from the current session's bars (from 09:30 ET
    onward on the most recent trading day in the DataFrame). Using multi-day
    data causes the cumulative VWAP to converge to a multi-day average price,
    making deviations appear artificially large and triggering false signals.

    min_deviation_pct  — minimum % price must deviate from VWAP to fire a signal.
                         Defaults to VWAP_MIN_DEVIATION_PCT from .env (0.5%).
    sensitivity        — controls how quickly signal strength grows with deviation.
                         Lower = more sensitive. Defaults to VWAP_SENSITIVITY (3.0).
    """
    _min_dev = (min_deviation_pct if min_deviation_pct is not None
                else config.VWAP_MIN_DEVIATION_PCT) / 100.0   # convert % to fraction
    _sensitivity = sensitivity if sensitivity is not None else config.VWAP_SENSITIVITY

    required_cols = {"open", "high", "low", "close", "volume"}
    if not required_cols.issubset(df.columns):
        return {"signal": "neutral", "strength": 0.0, "reason": "missing OHLCV columns for VWAP"}
    if df.empty:
        return {"signal": "neutral", "strength": 0.0, "reason": "empty dataframe for VWAP"}

    # ── Filter to today's session only ───────────────────────────────────────
    # The DataFrame index is timezone-aware UTC; convert to ET to find the
    # session boundary (09:30 ET on the date of the most recent bar).
    last_bar_et = df.index[-1].astimezone(_ET)
    session_open = last_bar_et.replace(hour=9, minute=30, second=0, microsecond=0)
    session_df = df[df.index >= session_open]

    if len(session_df) < 2:
        return {
            "signal": "neutral",
            "strength": 0.0,
            "reason": (
                f"only {len(session_df)} bar(s) in today's session — "
                "insufficient for reliable VWAP"
            ),
        }

    typical_price = (session_df["high"] + session_df["low"] + session_df["close"]) / 3
    cumulative_tp_vol = (typical_price * session_df["volume"]).cumsum()
    cumulative_vol = session_df["volume"].cumsum()
    vwap = cumulative_tp_vol / cumulative_vol

    current_price = session_df["close"].iloc[-1]
    current_vwap = vwap.iloc[-1]

    deviation_pct = (current_price - current_vwap) / current_vwap

    last_candle_bullish = session_df["close"].iloc[-1] > session_df["open"].iloc[-1]
    last_candle_bearish = session_df["close"].iloc[-1] < session_df["open"].iloc[-1]

    abs_dev = abs(deviation_pct)
    raw_strength = _clamp(abs_dev / (_sensitivity / 100.0))

    if deviation_pct > _min_dev and last_candle_bullish:
        strength = _clamp(0.45 + raw_strength * 0.4)
        signal: SignalValue = "buy" if strength >= 0.5 else "neutral"
        reason = f"Price {deviation_pct*100:.2f}% above VWAP with bullish candle"
    elif deviation_pct < -_min_dev and last_candle_bearish:
        strength = _clamp(0.45 + raw_strength * 0.4)
        signal = "sell" if strength >= 0.5 else "neutral"
        reason = f"Price {abs(deviation_pct)*100:.2f}% below VWAP with bearish candle"
    elif abs_dev < 0.002:
        strength = 0.2
        signal = "neutral"
        reason = f"Price hugging VWAP ({deviation_pct*100:.3f}% deviation)"
    else:
        strength = raw_strength * 0.3
        signal = "neutral"
        reason = f"VWAP deviation {deviation_pct*100:.2f}% — no clear bias"

    return {
        "signal": signal,
        "strength": round(strength, 4),
        "reason": reason,
        "vwap": round(float(current_vwap), 4),
        "price": round(float(current_price), 4),
        "deviation_pct": round(float(deviation_pct * 100), 4),
        "params": {"min_deviation_pct": config.VWAP_MIN_DEVIATION_PCT, "sensitivity": _sensitivity},
    }


# ─── Strategy 3: EMA 50/200 Cross ─────────────────────────────────────────────

def get_ema_signal(
    df: pd.DataFrame,
    fast: int = None,
    slow: int = None,
) -> dict:
    """
    EMA fast/slow crossover (golden/death cross) with trend-following strength.
    Periods default to EMA_FAST / EMA_SLOW from .env (50/200).
    Common alternatives: 20/50 (faster, more signals), 100/200 (slower, fewer).
    """
    _fast = fast if fast is not None else config.EMA_FAST
    _slow = slow if slow is not None else config.EMA_SLOW

    min_bars = _slow + 5
    if len(df) < min_bars:
        return {
            "signal": "neutral",
            "strength": 0.0,
            "reason": f"insufficient data for EMA{_slow} (have {len(df)} bars, need {min_bars})",
        }

    close = df["close"]
    ema50 = _ema_series(close, _fast)
    ema200 = _ema_series(close, _slow)

    current_50 = ema50.iloc[-1]
    current_200 = ema200.iloc[-1]
    prev_50 = ema50.iloc[-2]
    prev_200 = ema200.iloc[-2]
    current_price = close.iloc[-1]

    golden_cross = prev_50 <= prev_200 and current_50 > current_200
    death_cross = prev_50 >= prev_200 and current_50 < current_200
    bullish_trend = current_50 > current_200
    bearish_trend = current_50 < current_200

    gap_pct = abs(current_50 - current_200) / current_price
    raw_strength = _clamp(gap_pct / 0.05)
    price_above_50 = current_price > current_50

    if golden_cross:
        strength = _clamp(0.70 + raw_strength * 0.2)
        signal: SignalValue = "buy"
        reason = f"Golden cross — EMA{_fast} crossed above EMA{_slow}"
    elif death_cross:
        strength = _clamp(0.70 + raw_strength * 0.2)
        signal = "sell"
        reason = f"Death cross — EMA{_fast} crossed below EMA{_slow}"
    elif bullish_trend and price_above_50:
        strength = _clamp(0.40 + raw_strength * 0.35)
        signal = "buy" if strength >= 0.5 else "neutral"
        reason = f"Bullish trend: EMA{_fast}({current_50:.2f}) > EMA{_slow}({current_200:.2f})"
    elif bearish_trend and not price_above_50:
        strength = _clamp(0.40 + raw_strength * 0.35)
        signal = "sell" if strength >= 0.5 else "neutral"
        reason = f"Bearish trend: EMA{_fast}({current_50:.2f}) < EMA{_slow}({current_200:.2f})"
    else:
        strength = raw_strength * 0.25
        signal = "neutral"
        reason = f"EMA{_fast}/{_slow} not aligned with price action"

    return {
        "signal": signal,
        "strength": round(strength, 4),
        "reason": reason,
        "ema_fast": round(float(current_50), 4),
        "ema_slow": round(float(current_200), 4),
        "gap_pct": round(float(gap_pct * 100), 4),
        "params": {"fast": _fast, "slow": _slow},
    }


# ─── Strategy 4: Price Action ─────────────────────────────────────────────────

def get_price_action_signal(df: pd.DataFrame) -> dict:
    """
    Price action analysis using candlestick structure and momentum.
    Uses hourly bars. No external indicators — pure price behaviour.

    Five components:
      1. Higher highs / higher lows (structure)    max +0.25
      2. Momentum candle vs 20-bar average          max +0.20
      3. Support / resistance proximity             max +0.20
      4. Closing position in candle                 max +0.15
      5. Consecutive candles                        max +0.10
    """
    if len(df) < 22:
        return {
            "signal": "neutral",
            "strength": 0.0,
            "reason": "insufficient data for price action (need 22 bars)",
        }

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    opens = df["open"].values

    buy_score = 0.0
    sell_score = 0.0
    factors: dict = {}

    # 1 ── Higher highs / higher lows ────────────────────────────────────────
    recent_highs = highs[-6:]
    recent_lows = lows[-6:]
    swing_highs = [recent_highs[i] for i in range(1, len(recent_highs) - 1)
                   if recent_highs[i] >= recent_highs[i - 1] and recent_highs[i] >= recent_highs[i + 1]]
    swing_lows = [recent_lows[i] for i in range(1, len(recent_lows) - 1)
                  if recent_lows[i] <= recent_lows[i - 1] and recent_lows[i] <= recent_lows[i + 1]]

    hh_hl = False
    ll_lh = False
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        if swing_highs[-1] > swing_highs[-2] and swing_lows[-1] > swing_lows[-2]:
            buy_score += 0.25
            hh_hl = True
            factors["structure"] = "bullish (HH/HL)"
        elif swing_highs[-1] < swing_highs[-2] and swing_lows[-1] < swing_lows[-2]:
            sell_score += 0.25
            ll_lh = True
            factors["structure"] = "bearish (LH/LL)"
        else:
            factors["structure"] = "mixed"
    else:
        factors["structure"] = "insufficient swing points"

    # 2 ── Momentum candle ───────────────────────────────────────────────────
    body_sizes = np.abs(closes[-20:] - opens[-20:])
    avg_body = float(np.mean(body_sizes[:-1]))
    last_body = float(body_sizes[-1])
    last_bullish = closes[-1] > opens[-1]
    last_bearish = closes[-1] < opens[-1]

    momentum_candle = False
    if avg_body > 0 and last_body > 1.5 * avg_body:
        if last_bullish:
            buy_score += 0.20
            momentum_candle = True
            factors["momentum"] = f"bullish momentum candle ({last_body/avg_body:.1f}x avg)"
        elif last_bearish:
            sell_score += 0.20
            momentum_candle = True
            factors["momentum"] = f"bearish momentum candle ({last_body/avg_body:.1f}x avg)"
    else:
        factors["momentum"] = "no momentum candle"

    # 3 ── Support / resistance proximity ────────────────────────────────────
    swing_high = float(np.max(highs[-20:]))
    swing_low = float(np.min(lows[-20:]))
    current_price = float(closes[-1])

    near_support = abs(current_price - swing_low) / swing_low <= 0.005
    near_resistance = abs(current_price - swing_high) / swing_high <= 0.005

    if near_support and last_bullish:
        buy_score += 0.20
        factors["sr_proximity"] = f"near support ({swing_low:.2f}) with bullish candle"
    elif near_resistance and last_bearish:
        sell_score += 0.20
        factors["sr_proximity"] = f"near resistance ({swing_high:.2f}) with bearish candle"
    else:
        factors["sr_proximity"] = "not at key level"

    # 4 ── Closing position in candle ─────────────────────────────────────────
    close_positions = []
    for i in [-2, -1]:
        rng = highs[i] - lows[i]
        cp = (closes[i] - lows[i]) / rng if rng > 0 else 0.5
        close_positions.append(cp)

    if all(cp >= 0.7 for cp in close_positions):
        buy_score += 0.15
        factors["close_position"] = f"closing near top (avg {mean(close_positions):.2f})"
    elif all(cp <= 0.3 for cp in close_positions):
        sell_score += 0.15
        factors["close_position"] = f"closing near bottom (avg {mean(close_positions):.2f})"
    else:
        factors["close_position"] = f"neutral close positions"

    # 5 ── Consecutive candles ────────────────────────────────────────────────
    last3_bullish = all(closes[i] > opens[i] for i in [-3, -2, -1])
    last3_bearish = all(closes[i] < opens[i] for i in [-3, -2, -1])

    consecutive_candles = False
    if last3_bullish:
        buy_score += 0.10
        consecutive_candles = True
        factors["consecutive"] = "3 bullish candles"
    elif last3_bearish:
        sell_score += 0.10
        consecutive_candles = True
        factors["consecutive"] = "3 bearish candles"
    else:
        factors["consecutive"] = "mixed candles"

    # ── Final signal ─────────────────────────────────────────────────────────
    if buy_score >= 0.45 and buy_score > sell_score:
        signal: SignalValue = "buy"
        strength = _clamp(buy_score)
        reason = f"Price action bullish: {buy_score:.2f} buy / {sell_score:.2f} sell"
    elif sell_score >= 0.45 and sell_score > buy_score:
        signal = "sell"
        strength = _clamp(sell_score)
        reason = f"Price action bearish: {sell_score:.2f} sell / {buy_score:.2f} buy"
    else:
        signal = "neutral"
        strength = _clamp(max(buy_score, sell_score))
        reason = f"Price action neutral: buy={buy_score:.2f} sell={sell_score:.2f}"

    return {
        "signal": signal,
        "strength": round(strength, 4),
        "reason": reason,
        "buy_score": round(buy_score, 4),
        "sell_score": round(sell_score, 4),
        "hh_hl": hh_hl,
        "ll_lh": ll_lh,
        "momentum_candle": momentum_candle,
        "near_support": near_support,
        "near_resistance": near_resistance,
        "close_positions": [round(cp, 3) for cp in close_positions],
        "consecutive_candles": consecutive_candles,
        "swing_high": round(swing_high, 4),
        "swing_low": round(swing_low, 4),
        "factors": factors,
    }


# ─── Signal Confirmation Engine ───────────────────────────────────────────────

class SignalConfirmationEngine:
    """
    Evaluates whether enough strategies agree to justify a trade entry.

    STRICT MODE:
      Each strategy gets exactly one vote: buy, sell, or abstain.
      A strategy abstains if its signal is neutral OR strength < min_strength.
      Trade triggers if buy_votes >= min_required (long)
                     or sell_votes >= min_required (short, if allow_shorts).

    WEIGHTED MODE:
      Each strategy contributes its strength score if above min_strength.
      Weighted votes are summed.
      Trade triggers if weighted_buy_votes  >= min_required * 0.6
                     or weighted_sell_votes >= min_required * 0.6
      Allows a very strong signal from 2 strategies to sometimes outweigh
      a weak signal from a 3rd.
    """

    def __init__(
        self,
        min_required: int = 3,
        min_strength: float = 0.55,
        mode: str = "strict",
        allow_shorts: bool = True,
    ) -> None:
        self.min_required = min_required
        self.min_strength = min_strength
        self.mode = mode
        self.allow_shorts = allow_shorts

    def evaluate(
        self,
        macd_signal: dict,
        vwap_signal: dict,
        ema_signal: dict,
        price_action_signal: dict,
    ) -> dict:
        return evaluate_confirmation(
            macd_signal=macd_signal,
            vwap_signal=vwap_signal,
            ema_signal=ema_signal,
            price_action_signal=price_action_signal,
            min_required=self.min_required,
            min_strength=self.min_strength,
            mode=self.mode,
            allow_shorts=self.allow_shorts,
        )


def evaluate_confirmation(
    macd_signal: dict,
    vwap_signal: dict,
    ema_signal: dict,
    price_action_signal: dict,
    min_required: int = 3,
    min_strength: float = 0.55,
    mode: str = "strict",
    allow_shorts: bool = True,
) -> dict:
    """
    Returns a full confirmation report aggregating all four strategy signals.
    """

    # 1 ── Build vote table ─────────────────────────────────────────────────
    raw_inputs = [
        ("macd",         macd_signal),
        ("vwap",         vwap_signal),
        ("ema_cross",    ema_signal),
        ("price_action", price_action_signal),
    ]

    votes = []
    for name, sig in raw_inputs:
        signal_val: SignalValue = sig.get("signal", "neutral")
        strength: float = float(sig.get("strength", 0.0))
        reason: str = sig.get("reason", "")

        if signal_val == "neutral" or strength < min_strength:
            vote = "abstain"
        else:
            vote = signal_val  # "buy" or "sell"

        votes.append({
            "strategy": name,
            "vote": vote,
            "signal": signal_val,
            "strength": round(strength, 4),
            "reason": reason,
        })

    # 2 ── Count votes ──────────────────────────────────────────────────────
    buy_votes = [v for v in votes if v["vote"] == "buy"]
    sell_votes = [v for v in votes if v["vote"] == "sell"]
    abstentions = [v for v in votes if v["vote"] == "abstain"]

    buy_count = len(buy_votes)
    sell_count = len(sell_votes)
    abstain_count = len(abstentions)

    weighted_buy = sum(v["strength"] for v in buy_votes)
    weighted_sell = sum(v["strength"] for v in sell_votes)
    weighted_threshold = min_required * 0.6

    # 3 & 4 ── Direction decision ───────────────────────────────────────────
    if mode == "weighted":
        if weighted_buy >= weighted_threshold and weighted_buy > weighted_sell:
            direction = "buy"
            confirming = buy_votes
            conflicting = sell_votes
        elif weighted_sell >= weighted_threshold and weighted_sell > weighted_buy and allow_shorts:
            direction = "sell"
            confirming = sell_votes
            conflicting = buy_votes
        else:
            direction = "no_trade"
            confirming = []
            conflicting = []
    else:  # strict
        if buy_count >= min_required:
            direction = "buy"
            confirming = buy_votes
            conflicting = sell_votes
        elif sell_count >= min_required and allow_shorts:
            direction = "sell"
            confirming = sell_votes
            conflicting = buy_votes
        else:
            direction = "no_trade"
            confirming = []
            conflicting = []

    confirmed = direction != "no_trade"
    confirming_count = len(confirming)

    # 5 ── Confirmation quality grade ──────────────────────────────────────
    if confirmed and confirming:
        avg_strength = mean(v["strength"] for v in confirming)
    else:
        avg_strength = 0.0

    if not confirmed:
        quality = "F"
    elif confirming_count == 4 and avg_strength >= 0.75:
        quality = "A"
    elif confirming_count >= 3 and avg_strength >= 0.65:
        quality = "B"
    elif confirming_count >= min_required and avg_strength >= 0.55:
        quality = "C"
    else:
        quality = "F"

    # 6 ── Human-readable summary ──────────────────────────────────────────
    strategy_labels = {
        "macd":         "MACD",
        "vwap":         "VWAP",
        "ema_cross":    "EMA",
        "price_action": "PriceAction",
    }

    def _vote_symbol(v: dict) -> str:
        if v["vote"] == "buy":
            return f"{strategy_labels[v['strategy']]} ✓"
        elif v["vote"] == "sell":
            return f"{strategy_labels[v['strategy']]} ✓"
        else:
            return f"{strategy_labels[v['strategy']]} ✗"

    vote_line = "  ".join(_vote_symbol(v) for v in votes)
    total = len(votes)

    confirming_names = [v["strategy"] for v in confirming]
    conflicting_names = [v["strategy"] for v in conflicting]
    abstaining_names = [v["strategy"] for v in abstentions]

    # Warn if price action is the sole confirmer
    pa_only_warning = ""
    if confirmed and confirming_names == ["price_action"]:
        pa_only_warning = " ⚠ price action is the sole confirmer — treat with caution"

    if confirmed and confirming_count == 4:
        summary = (
            f"4/4 strategies confirm {direction.upper()} — full confluence — "
            f"Grade {quality} setup{pa_only_warning}"
        )
    elif confirmed:
        conflict_note = ""
        if conflicting_names:
            conflict_labels = [strategy_labels[n] for n in conflicting_names]
            confirm_labels = [strategy_labels[n] for n in confirming_names]
            conflict_note = f" — conflict: {', '.join(conflict_labels)} say opposite"
        summary = (
            f"{confirming_count}/{total} strategies confirm {direction.upper()} — "
            f"{vote_line}{conflict_note} — Grade {quality}{pa_only_warning}"
        )
    else:
        if buy_count > 0 and sell_count > 0:
            conflict_labels_buy = [strategy_labels[v["strategy"]] for v in buy_votes]
            conflict_labels_sell = [strategy_labels[v["strategy"]] for v in sell_votes]
            summary = (
                f"Conflicting signals — {', '.join(conflict_labels_buy)} say BUY, "
                f"{', '.join(conflict_labels_sell)} say SELL — no trade"
            )
        else:
            side = "BUY" if buy_count > sell_count else "SELL"
            actual_count = max(buy_count, sell_count)
            summary = (
                f"{actual_count}/{total} strategies confirm {side} — "
                f"insufficient for entry (need {min_required})"
            )

    # 7 ── Return full report ──────────────────────────────────────────────
    return {
        "direction": direction,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "abstain_count": abstain_count,
        "min_required": min_required,
        "confirmed": confirmed,
        "quality": quality,
        "avg_confirming_strength": round(avg_strength, 4),
        "confirming_strategies": confirming_names,
        "conflicting_strategies": conflicting_names,
        "abstaining_strategies": abstaining_names,
        "votes": votes,
        "weighted_buy_score": round(weighted_buy, 4),
        "weighted_sell_score": round(weighted_sell, 4),
        "summary": summary,
        "allow_shorts": allow_shorts,
        "mode": mode,
        "signal_count": f"{confirming_count}/{total}",
    }
