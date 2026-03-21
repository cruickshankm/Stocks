"""
Claude AI decision engine.

Sends market data, strategy signals, and the full confirmation report to
Claude and returns a structured trade decision.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

import config

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


# ─── Prompt builders ──────────────────────────────────────────────────────────

def _build_confirmation_block(report: dict) -> str:
    votes = report.get("votes", [])
    rows = []
    for v in votes:
        label = v["strategy"].replace("_", " ").upper().ljust(14)
        rows.append(
            f"  {label} [{v['vote'].upper():7s}]  "
            f"strength: {v['strength']:.2f}  — {v['reason']}"
        )
    vote_breakdown = "\n".join(rows)

    total = len(votes)
    buy_count = report["buy_count"]
    direction = report["direction"].upper()

    return f"""\
SIGNAL CONFIRMATION REPORT ({buy_count}/{total} strategies confirm):
Direction: {direction}
Quality grade: {report['quality']}
Confirmed: {report['confirmed']}
Mode: {report['mode']} (min required: {report['min_required']})

VOTE BREAKDOWN:
{vote_breakdown}

Confirming:  {report['confirming_strategies']}
Conflicting: {report['conflicting_strategies']}
Abstaining:  {report['abstaining_strategies']}

Summary: {report['summary']}

INSTRUCTION:
  If confirmed=True and quality is A or B: strongly favour the direction.
  If confirmed=True and quality is C: proceed cautiously, note risks.
  If confirmed=False: default to HOLD unless you have a very strong
  fundamental reason to override — and you must explain why in detail.
  The confirmation engine is the gatekeeper — overriding a no_trade
  confirmation is a high bar and must be justified with specific evidence.\
"""


_SYSTEM_PROMPT = """\
You are an expert algorithmic trading analyst. Your job is to review market data,
technical strategy signals, and a multi-strategy confirmation report, then make
a final trade recommendation.

You must respond ONLY with a valid JSON object — no markdown, no preamble, no
extra text. The JSON must match this exact schema:

{
  "action":                  "buy" | "sell" | "hold",
  "confidence":              float (0.0 – 1.0),
  "reasoning":               string (concise explanation),
  "stop_loss_pct":           float (suggested stop loss %),
  "take_profit_pct":         float (suggested take profit %),
  "position_size_modifier":  float (0.5 = half size, 1.0 = full, 1.5 = larger),
  "confirmation_quality":    "A" | "B" | "C" | "F",
  "signal_count":            string (e.g. "3/4"),
  "overriding_confirmation": bool,
  "override_reason":         string or null
}

Rules:
- If the confirmation report says confirmed=False, your default action must be
  "hold". Only set action to "buy" or "sell" if you have a compelling,
  specific, articulable reason — and set overriding_confirmation=true with a
  detailed override_reason.
- Never invent data. Base your decision on what you are given.
- Be conservative with position_size_modifier: Grade A → up to 1.2,
  Grade B → 1.0, Grade C → 0.75, overriding → 0.5.\
"""


def _build_user_prompt(
    symbol: str,
    bar_summary: dict,
    confirmation_report: dict,
    portfolio_context: dict | None = None,
) -> str:
    confirmation_block = _build_confirmation_block(confirmation_report)

    portfolio_section = ""
    if portfolio_context:
        portfolio_section = f"""
PORTFOLIO CONTEXT:
  Buying power: ${portfolio_context.get('buying_power', 0):,.2f}
  Portfolio value: ${portfolio_context.get('portfolio_value', 0):,.2f}
  Open positions: {portfolio_context.get('open_positions', 0)}
  Current position in {symbol}: {portfolio_context.get('current_position', 'none')}
"""

    return f"""\
SYMBOL: {symbol}

PRICE SUMMARY:
  Current price:   ${bar_summary.get('current_price', 0):,.4f}
  Daily open:      ${bar_summary.get('daily_open', 0):,.4f}
  Daily high:      ${bar_summary.get('daily_high', 0):,.4f}
  Daily low:       ${bar_summary.get('daily_low', 0):,.4f}
  Daily change:    {bar_summary.get('daily_change_pct', 0):+.2f}%
  Avg volume:      {bar_summary.get('avg_volume', 0):,.0f}
  Volume ratio:    {bar_summary.get('volume_ratio', 1.0):.2f}x avg
{portfolio_section}
{confirmation_block}

Based on all of the above, provide your trade decision as JSON.\
"""


# ─── Main entry point ─────────────────────────────────────────────────────────

def get_trade_decision(
    symbol: str,
    bar_summary: dict,
    confirmation_report: dict,
    portfolio_context: dict | None = None,
) -> dict[str, Any]:
    """
    Calls Claude with the full market context and returns a structured decision.

    Returns a dict with keys: action, confidence, reasoning, stop_loss_pct,
    take_profit_pct, position_size_modifier, confirmation_quality, signal_count,
    overriding_confirmation, override_reason, plus a 'raw_response' for logging.
    """
    user_prompt = _build_user_prompt(
        symbol=symbol,
        bar_summary=bar_summary,
        confirmation_report=confirmation_report,
        portfolio_context=portfolio_context,
    )

    logger.debug("Sending request to Claude for %s", symbol)

    try:
        response = _client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.APIError as exc:
        logger.error("Claude API error for %s: %s", symbol, exc)
        raise

    raw_text = response.content[0].text.strip()

    try:
        decision = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("Claude returned non-JSON for %s: %s\n%s", symbol, exc, raw_text)
        decision = {
            "action": "hold",
            "confidence": 0.0,
            "reasoning": f"JSON parse error: {exc}",
            "stop_loss_pct": config.STOP_LOSS_PCT,
            "take_profit_pct": config.TAKE_PROFIT_PCT,
            "position_size_modifier": 0.5,
            "confirmation_quality": confirmation_report.get("quality", "F"),
            "signal_count": confirmation_report.get("signal_count", "0/4"),
            "overriding_confirmation": False,
            "override_reason": None,
        }

    decision["raw_response"] = raw_text
    decision["symbol"] = symbol

    logger.info(
        "Claude decision for %s: action=%s confidence=%.2f quality=%s overriding=%s",
        symbol,
        decision.get("action", "?"),
        decision.get("confidence", 0.0),
        decision.get("confirmation_quality", "?"),
        decision.get("overriding_confirmation", False),
    )

    return decision
