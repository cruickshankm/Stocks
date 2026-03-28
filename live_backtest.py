"""
Live-style backtester — simulates the portfolio exactly as the live bot runs it.

Key difference from backtester.py:
  - All symbols are advanced one bar at a time together, just like the live
    scanner processes every symbol on each 60-second tick.
  - A single shared capital pool is used across all symbols.
  - MAX_OPEN_POSITIONS is enforced globally: no new entry is taken once 6
    positions are open, regardless of which symbol signals.
  - Position sizing uses the CURRENT portfolio value at entry time, so wins
    and losses compound correctly across the session.
  - Grade-based position_size_modifier (A=1.0, B=0.9, C=0.75) is applied,
    matching the USE_AI=false path in main.py.

Usage (via main.py):
    python main.py --live-backtest
    python main.py --live-backtest --start 2026-01-01 --end 2026-03-19
    python main.py --live-backtest --capital 100000 --timeframe 1Hour
    python main.py --live-backtest --symbol SLV,USO,GDX --start 2026-01-01
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich import box

from strategies import (
    get_macd_signal,
    get_vwap_signal,
    get_ema_signal,
    get_price_action_signal,
    evaluate_confirmation,
    get_trend_direction,
)
import config

log = logging.getLogger(__name__)
console = Console(highlight=False)

WARMUP_BARS = config.EMA_SLOW + 10

# Grade → position_size_modifier, matching main.py USE_AI=false path
_GRADE_MODIFIER = {"A": 1.0, "B": 0.9, "C": 0.75}


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class SimTrade:
    symbol: str
    direction: str          # "long" | "short"
    entry_bar: int          # global bar index (position in the merged timeline)
    entry_time: datetime
    entry_price: float
    stop_price: float       # initial hard stop (kept for reference; trailing stop used in sim)
    target_price: float
    shares: int
    grade: str
    signal_count: str
    confirmed: bool
    trail_pct: float = 0.05             # trailing stop percentage (matches STOP_LOSS_PCT)
    trail_high: float = 0.0             # best price seen since entry (long: highest high)
    trail_low: float = float("inf")     # best price seen since entry (short: lowest low)

    exit_bar: Optional[int] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None   # "stop" | "target" | "end_of_data"

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        if self.direction == "long":
            return (self.exit_price - self.entry_price) * self.shares
        else:
            return (self.entry_price - self.exit_price) * self.shares

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None or self.entry_price == 0:
            return 0.0
        if self.direction == "long":
            return (self.exit_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - self.exit_price) / self.entry_price

    @property
    def hold_bars(self) -> int:
        if self.exit_bar is None:
            return 0
        return self.exit_bar - self.entry_bar


@dataclass
class LiveBacktestResult:
    symbols: list[str]
    start_date: str
    end_date: str
    timeframe: str
    mode: str
    min_required: int
    min_strength: float
    initial_capital: float
    trades: list[SimTrade] = field(default_factory=list)

    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    equity_curve: list[float] = field(default_factory=list)

    def finalise(self) -> None:
        self._compute_equity_curve()
        self._compute_drawdown()
        self._compute_sharpe()

    @property
    def closed_trades(self) -> list[SimTrade]:
        return [t for t in self.trades if not t.is_open]

    @property
    def win_trades(self) -> list[SimTrade]:
        return [t for t in self.closed_trades if t.pnl > 0]

    @property
    def loss_trades(self) -> list[SimTrade]:
        return [t for t in self.closed_trades if t.pnl <= 0]

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_trades)

    @property
    def win_rate(self) -> float:
        n = len(self.closed_trades)
        return len(self.win_trades) / n if n > 0 else 0.0

    @property
    def avg_win(self) -> float:
        w = self.win_trades
        return sum(t.pnl for t in w) / len(w) if w else 0.0

    @property
    def avg_loss(self) -> float:
        l = self.loss_trades
        return sum(t.pnl for t in l) / len(l) if l else 0.0

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl for t in self.win_trades)
        gross_loss = abs(sum(t.pnl for t in self.loss_trades))
        return gross_win / gross_loss if gross_loss > 0 else float("inf")

    @property
    def avg_hold_bars(self) -> float:
        n = self.closed_trades
        return sum(t.hold_bars for t in n) / len(n) if n else 0.0

    def trades_by_grade(self, grade: str) -> list[SimTrade]:
        return [t for t in self.closed_trades if t.grade == grade]

    def trades_for_symbol(self, symbol: str) -> list[SimTrade]:
        return [t for t in self.closed_trades if t.symbol == symbol]

    def _compute_equity_curve(self) -> None:
        capital = self.initial_capital
        curve = [capital]
        # Walk trades in close order so the curve reflects actual timing
        closed_sorted = sorted(self.closed_trades, key=lambda t: t.exit_bar or 0)
        for t in closed_sorted:
            capital += t.pnl
            curve.append(capital)
        self.equity_curve = curve
        self.total_return_pct = (
            (capital - self.initial_capital) / self.initial_capital
            if self.initial_capital > 0 else 0.0
        )

    def _compute_drawdown(self) -> None:
        if not self.equity_curve:
            return
        peak = self.equity_curve[0]
        max_dd = 0.0
        for v in self.equity_curve:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        self.max_drawdown_pct = max_dd

    def _compute_sharpe(self, risk_free_rate: float = 0.05) -> None:
        returns = [t.pnl_pct for t in self.closed_trades]
        if len(returns) < 2:
            self.sharpe_ratio = float("nan")
            return
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance)
        annualisation = math.sqrt(1638)
        daily_rf = risk_free_rate / 252
        if std_r < 1e-8:
            self.sharpe_ratio = float("nan")
        else:
            self.sharpe_ratio = (mean_r - daily_rf) / std_r * annualisation


# ─── Data fetching ────────────────────────────────────────────────────────────

def _fetch_bars(
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe: str,
) -> pd.DataFrame:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed

    client = StockHistoricalDataClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
    )
    tf_map = {
        "1Min":  TimeFrame(1,  TimeFrameUnit.Minute),
        "5Min":  TimeFrame(5,  TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1,  TimeFrameUnit.Hour),
        "1Day":  TimeFrame(1,  TimeFrameUnit.Day),
    }
    tf = tf_map.get(timeframe, TimeFrame(1, TimeFrameUnit.Hour))
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=start,
        end=end,
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(req)
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level=0)
    df = df.rename(columns=str.lower)
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


# ─── Exit checker ─────────────────────────────────────────────────────────────

def _check_exits(trade: SimTrade, bar: pd.Series, bar_idx: int) -> Optional[str]:
    """
    Check fixed stop/target against bar high/low. Sets exit fields in-place.
    Stop is checked before target (conservative — assumes worst fills intra-bar).
    """
    if trade.direction == "long":
        if bar["low"] <= trade.stop_price:
            trade.exit_price  = trade.stop_price
            trade.exit_reason = "stop"
            trade.exit_bar    = bar_idx
            trade.exit_time   = bar.name
            return "stop"
        if bar["high"] >= trade.target_price:
            trade.exit_price  = trade.target_price
            trade.exit_reason = "target"
            trade.exit_bar    = bar_idx
            trade.exit_time   = bar.name
            return "target"
    else:
        if bar["high"] >= trade.stop_price:
            trade.exit_price  = trade.stop_price
            trade.exit_reason = "stop"
            trade.exit_bar    = bar_idx
            trade.exit_time   = bar.name
            return "stop"
        if bar["low"] <= trade.target_price:
            trade.exit_price  = trade.target_price
            trade.exit_reason = "target"
            trade.exit_bar    = bar_idx
            trade.exit_time   = bar.name
            return "target"
    return None


# ─── Core simulation ──────────────────────────────────────────────────────────

def run_live_backtest(
    symbols: list[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timeframe: str = "1Hour",
    initial_capital: float = 100_000.0,
    min_required: Optional[int] = None,
    min_strength: Optional[float] = None,
    mode: Optional[str] = None,
    allow_shorts: Optional[bool] = None,
    stop_loss_pct: Optional[float] = None,
    take_profit_pct: Optional[float] = None,
    max_position_pct: Optional[float] = None,
    max_open_positions: Optional[int] = None,
    min_grade: str = "C",
) -> LiveBacktestResult:
    """
    Simulate live trading across all symbols simultaneously.

    For each bar timestamp that appears in ANY symbol's data:
      1. Check exits for all currently open positions.
      2. For each symbol that has a bar at this timestamp AND has no open
         position AND the portfolio has a free slot: run the strategy window
         and look for a new entry signal.
      3. Execute at the next bar's open (no lookahead).

    This mirrors exactly how the live bot works: every scan tick processes
    all symbols in parallel under a single shared position limit.

    min_grade: lowest confirmation grade allowed to trade ("A", "B", or "C").
      "C" = trade everything confirmed (default, matches live bot)
      "B" = skip Grade C signals — only take B and A setups
      "A" = only take A-grade (full 4-strategy confluence) setups
    """
    _grade_rank = {"A": 3, "B": 2, "C": 1}
    _min_grade_rank = _grade_rank.get(min_grade.upper(), 1)

    _min_req   = min_required    if min_required    is not None else config.MIN_SIGNALS_REQUIRED
    _min_str   = min_strength    if min_strength    is not None else config.MIN_SIGNAL_STRENGTH
    _mode      = mode            or config.CONFIRMATION_MODE
    _shorts    = allow_shorts    if allow_shorts    is not None else config.ALLOW_SHORTS
    _stop      = stop_loss_pct   or config.STOP_LOSS_PCT
    _target    = take_profit_pct or config.TAKE_PROFIT_PCT
    _max_pos   = max_position_pct  or config.MAX_POSITION_SIZE
    _max_slots = max_open_positions if max_open_positions is not None else config.MAX_OPEN_POSITIONS

    tz = timezone.utc
    end_dt = (
        datetime.now(tz) - timedelta(hours=1)
        if not end_date
        else datetime.fromisoformat(end_date).replace(tzinfo=tz)
    )
    start_dt = (
        end_dt - timedelta(days=180)
        if not start_date
        else datetime.fromisoformat(start_date).replace(tzinfo=tz)
    )
    warmup_start = start_dt - timedelta(days=60)

    # ── Fetch data for all symbols ────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold cyan]LIVE-STYLE BACKTEST[/bold cyan]"))
    console.print(
        f"  Period    : [white]{start_dt.date()} to {end_dt.date()}[/white]\n"
        f"  Symbols   : [white]{', '.join(symbols)}[/white]\n"
        f"  Timeframe : [white]{timeframe}[/white]   "
        f"Capital: [white]${initial_capital:,.0f}[/white]   "
        f"Max positions: [white]{_max_slots}[/white]   "
        f"Min grade: [white]{min_grade.upper()}[/white]"
    )
    console.print()

    bars: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        console.print(f"  Fetching {sym} ...", end=" ")
        try:
            df = _fetch_bars(sym, warmup_start, end_dt, timeframe)
            bars[sym] = df
            console.print(f"[green]{len(df)} bars[/green]")
        except Exception as exc:
            console.print(f"[red]FAILED — {exc}[/red]")

    if not bars:
        console.print("[red]No data fetched — aborting.[/red]")
        raise RuntimeError("No data available for any symbol")

    # ── Build a sorted union of all bar timestamps in the backtest window ─────
    start_ts = pd.Timestamp(start_dt)
    all_timestamps: list[pd.Timestamp] = sorted(
        set(
            ts
            for df in bars.values()
            for ts in df.index
            if ts >= start_ts
        )
    )

    console.print(f"\n  {len(all_timestamps):,} unique bar timestamps across all symbols\n")

    result = LiveBacktestResult(
        symbols=symbols,
        start_date=str(start_dt.date()),
        end_date=str(end_dt.date()),
        timeframe=timeframe,
        mode=_mode,
        min_required=_min_req,
        min_strength=_min_str,
        initial_capital=initial_capital,
    )

    capital = initial_capital
    # symbol → currently open SimTrade (None if flat)
    open_positions: dict[str, Optional[SimTrade]] = {sym: None for sym in bars}
    # global bar counter used as the bar_idx reference for hold_bars
    bar_counter = 0

    for ts in all_timestamps:
        bar_counter += 1

        # ── 1. Process exits for every open position ──────────────────────────
        for sym, trade in list(open_positions.items()):
            if trade is None or not trade.is_open:
                continue
            df = bars[sym]
            if ts not in df.index:
                continue
            bar = df.loc[ts]
            # Skip the exact entry bar — don't let stop/target fire on entry
            if bar_counter <= trade.entry_bar:
                continue
            exit_reason = _check_exits(trade, bar, bar_counter)
            if exit_reason:
                capital += trade.pnl
                open_positions[sym] = None

        # Count how many slots are currently occupied
        open_count = sum(1 for t in open_positions.values() if t is not None)

        # ── 2. Look for new entries on any symbol that is flat ────────────────
        # Shuffle order each bar so no symbol has a systematic priority
        # advantage when the portfolio is near capacity.
        import random
        candidate_symbols = [
            sym for sym in bars
            if open_positions[sym] is None and ts in bars[sym].index
        ]
        random.shuffle(candidate_symbols)

        for sym in candidate_symbols:
            if open_count >= _max_slots:
                break

            df = bars[sym]
            ts_loc = df.index.get_loc(ts)

            # Need at least WARMUP_BARS of history before this bar
            if ts_loc < WARMUP_BARS:
                continue

            # Ensure the bar at ts is not within warmup of the absolute start
            if ts < start_ts:
                continue

            # Strategy window = all bars up to and including the current bar
            window = df.iloc[: ts_loc + 1]

            try:
                macd_sig = get_macd_signal(window)
                vwap_sig = get_vwap_signal(window)
                ema_sig  = get_ema_signal(window)
                pa_sig   = get_price_action_signal(window)
            except Exception as exc:
                log.debug("Strategy error %s @ %s: %s", sym, ts, exc)
                continue

            report = evaluate_confirmation(
                macd_signal=macd_sig,
                vwap_signal=vwap_sig,
                ema_signal=ema_sig,
                price_action_signal=pa_sig,
                min_required=_min_req,
                min_strength=_min_str,
                mode=_mode,
                allow_shorts=_shorts,
            )

            if not report["confirmed"]:
                continue

            direction = report["direction"]
            if direction not in ("buy", "sell"):
                continue

            # Trend pre-filter: skip signals that oppose the macro session trend
            if config.TREND_FILTER_ENABLED:
                trend = get_trend_direction(window, config.TREND_FILTER_PERIOD)
                if (direction == "buy" and trend == "bear") or (direction == "sell" and trend == "bull"):
                    continue

            grade = report["quality"]
            size_modifier = _GRADE_MODIFIER.get(grade, 0.0)
            if size_modifier == 0.0:
                # Grade F with confirmed=True — not tradeable (matches live bot)
                continue
            if _grade_rank.get(grade, 0) < _min_grade_rank:
                # Below the minimum grade threshold requested
                continue

            # Entry at the next bar's open (no lookahead bias)
            if ts_loc + 1 >= len(df):
                continue
            next_bar = df.iloc[ts_loc + 1]
            entry_price = float(next_bar["open"])

            max_dollars = capital * _max_pos * size_modifier
            shares = max(int(max_dollars / entry_price), 1)

            if direction == "buy":
                stop_price   = round(entry_price * (1 - _stop),   4)
                target_price = round(entry_price * (1 + _target),  4)
                sim_dir = "long"
            else:
                stop_price   = round(entry_price * (1 + _stop),   4)
                target_price = round(entry_price * (1 - _target),  4)
                sim_dir = "short"

            trade = SimTrade(
                symbol=sym,
                direction=sim_dir,
                entry_bar=bar_counter + 1,  # entry is on the NEXT bar
                entry_time=next_bar.name,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                shares=shares,
                grade=grade,
                signal_count=report["signal_count"],
                confirmed=True,
                trail_pct=_stop,
                trail_high=entry_price,   # initialise at entry so trail starts from entry
                trail_low=entry_price,
            )
            open_positions[sym] = trade
            result.trades.append(trade)
            open_count += 1

    # ── 3. Close anything still open at end of data ───────────────────────────
    for sym, trade in open_positions.items():
        if trade is None or not trade.is_open:
            continue
        df = bars[sym]
        last_bar = df.iloc[-1]
        trade.exit_price = float(last_bar["close"])
        trade.exit_reason = "end_of_data"
        trade.exit_bar = bar_counter
        trade.exit_time = last_bar.name
        capital += trade.pnl
        open_positions[sym] = None

    result.finalise()
    return result


# ─── Report ───────────────────────────────────────────────────────────────────

def print_live_backtest_report(result: LiveBacktestResult) -> None:
    console.print()
    console.print(Rule("[bold bright_cyan]LIVE-STYLE BACKTEST RESULTS[/bold bright_cyan]"))

    n = len(result.closed_trades)
    ret_col   = "green" if result.total_return_pct >= 0 else "red"
    dd_col    = "green" if result.max_drawdown_pct < 0.05 else ("yellow" if result.max_drawdown_pct < 0.15 else "red")
    wr_col    = "green" if result.win_rate >= 0.55 else ("yellow" if result.win_rate >= 0.45 else "red")
    pf_col    = "green" if result.profit_factor >= 1.5 else ("yellow" if result.profit_factor >= 1.0 else "red")
    sharpe_v  = not math.isnan(result.sharpe_ratio)
    sh_col    = "green" if sharpe_v and result.sharpe_ratio >= 1.0 else ("yellow" if sharpe_v and result.sharpe_ratio >= 0.5 else "dim")
    sh_disp   = f"{result.sharpe_ratio:.2f}" if sharpe_v else "N/A"

    summary = Table(box=None, show_header=False, padding=(0, 3))
    summary.add_column("Key",    style="cyan",  no_wrap=True)
    summary.add_column("Value",  style="white")
    summary.add_column("Key2",   style="cyan",  no_wrap=True)
    summary.add_column("Value2", style="white")

    summary.add_row("Period",           f"{result.start_date}  to  {result.end_date}",
                    "Timeframe",        result.timeframe)
    summary.add_row("Symbols",          ", ".join(result.symbols),
                    "Mode",             f"{result.mode}  (min {result.min_required}/4, strength >= {result.min_strength})")
    summary.add_row("Initial capital",  f"${result.initial_capital:,.2f}",
                    "Final capital",    f"${result.initial_capital + result.total_pnl:,.2f}")
    summary.add_row("Total return",     f"[{ret_col}]{result.total_return_pct*100:+.2f}%[/{ret_col}]",
                    "Total P&L",        f"[{ret_col}]${result.total_pnl:+,.2f}[/{ret_col}]")
    summary.add_row("Max drawdown",     f"[{dd_col}]{result.max_drawdown_pct*100:.2f}%[/{dd_col}]",
                    "Sharpe ratio",     f"[{sh_col}]{sh_disp}[/{sh_col}]")
    summary.add_row("Total trades",     str(n),
                    "Avg hold",         f"{result.avg_hold_bars:.1f} bars")
    summary.add_row("Win rate",         f"[{wr_col}]{result.win_rate*100:.1f}%[/{wr_col}]",
                    "Profit factor",    f"[{pf_col}]{result.profit_factor:.2f}[/{pf_col}]")
    summary.add_row("Avg win",          f"[green]${result.avg_win:+,.2f}[/green]",
                    "Avg loss",         f"[red]${result.avg_loss:+,.2f}[/red]")

    console.print(Panel(summary, title="[bold]Portfolio Summary[/bold]", box=box.ROUNDED))

    # ── Per-symbol breakdown ──────────────────────────────────────────────────
    sym_table = Table(
        title="Results by Symbol",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=False,
    )
    sym_table.add_column("Symbol",    width=8)
    sym_table.add_column("Trades",    width=8,  justify="right")
    sym_table.add_column("Wins",      width=6,  justify="right")
    sym_table.add_column("Win %",     width=8,  justify="right")
    sym_table.add_column("Total P&L", width=12, justify="right")
    sym_table.add_column("Avg win",   width=10, justify="right")
    sym_table.add_column("Avg loss",  width=10, justify="right")
    sym_table.add_column("Verdict",   width=14)

    for sym in result.symbols:
        sym_trades = result.trades_for_symbol(sym)
        if not sym_trades:
            sym_table.add_row(
                f"[bold white]{sym}[/bold white]",
                "0", "—", "—", "—", "—", "—", "[dim]no trades[/dim]",
            )
            continue
        wins_s  = [t for t in sym_trades if t.pnl > 0]
        loss_s  = [t for t in sym_trades if t.pnl <= 0]
        wr_s    = len(wins_s) / len(sym_trades)
        pnl_s   = sum(t.pnl for t in sym_trades)
        avg_w   = sum(t.pnl for t in wins_s) / len(wins_s) if wins_s else 0.0
        avg_l   = sum(t.pnl for t in loss_s) / len(loss_s) if loss_s else 0.0
        wrc     = "green" if wr_s >= 0.55 else ("yellow" if wr_s >= 0.45 else "red")
        pnlc    = "green" if pnl_s >= 0 else "red"

        if pnl_s > 0 and wr_s >= 0.55:
            verdict = "[bright_green]Strong[/bright_green]"
        elif pnl_s > 0 and wr_s >= 0.45:
            verdict = "[green]Profitable[/green]"
        elif pnl_s > 0:
            verdict = "[yellow]Marginal[/yellow]"
        elif pnl_s < 0 and wr_s < 0.4:
            verdict = "[red]Avoid[/red]"
        else:
            verdict = "[red]Losing[/red]"

        sym_table.add_row(
            f"[bold white]{sym}[/bold white]",
            str(len(sym_trades)),
            str(len(wins_s)),
            f"[{wrc}]{wr_s*100:.1f}%[/{wrc}]",
            f"[{pnlc}]${pnl_s:+,.2f}[/{pnlc}]",
            f"[green]${avg_w:+,.2f}[/green]" if wins_s else "—",
            f"[red]${avg_l:+,.2f}[/red]" if loss_s else "—",
            verdict,
        )

    console.print(sym_table)

    # ── By grade ──────────────────────────────────────────────────────────────
    grade_table = Table(
        title="Performance by Confirmation Grade",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    grade_table.add_column("Grade",     width=8)
    grade_table.add_column("Trades",    width=8,  justify="right")
    grade_table.add_column("Wins",      width=6,  justify="right")
    grade_table.add_column("Win %",     width=8,  justify="right")
    grade_table.add_column("Total P&L", width=12, justify="right")

    for grade in ("A", "B", "C"):
        trades_g = result.trades_by_grade(grade)
        if not trades_g:
            continue
        wins_g   = [t for t in trades_g if t.pnl > 0]
        wr_g     = len(wins_g) / len(trades_g)
        pnl_g    = sum(t.pnl for t in trades_g)
        wrc      = "green" if wr_g >= 0.55 else ("yellow" if wr_g >= 0.4 else "red")
        pnlc     = "green" if pnl_g >= 0 else "red"
        grade_table.add_row(
            grade, str(len(trades_g)), str(len(wins_g)),
            f"[{wrc}]{wr_g*100:.1f}%[/{wrc}]",
            f"[{pnlc}]${pnl_g:+,.2f}[/{pnlc}]",
        )

    console.print(grade_table)

    # ── Exit reason breakdown ─────────────────────────────────────────────────
    stops   = [t for t in result.closed_trades if t.exit_reason == "stop"]
    targets = [t for t in result.closed_trades if t.exit_reason == "target"]
    eod     = [t for t in result.closed_trades if t.exit_reason == "end_of_data"]

    exit_table = Table(title="Exit Breakdown", box=box.ROUNDED, header_style="bold cyan")
    exit_table.add_column("Exit reason", width=16)
    exit_table.add_column("Count",       width=8,  justify="right")
    exit_table.add_column("Avg P&L",     width=12, justify="right")

    for label, group, colour in [
        ("Target hit",  targets, "green"),
        ("Stop hit",    stops,   "red"),
        ("End of data", eod,     "dim"),
    ]:
        if group:
            avg = sum(t.pnl for t in group) / len(group)
            exit_table.add_row(label, str(len(group)), f"[{colour}]${avg:+,.2f}[/{colour}]")

    console.print(exit_table)

    # ── All trades ────────────────────────────────────────────────────────────
    if result.closed_trades:
        trade_table = Table(
            title="All Trades  (chronological)",
            box=box.SIMPLE,
            header_style="bold cyan",
            show_lines=False,
        )
        trade_table.add_column("#",          width=4,  justify="right")
        trade_table.add_column("Symbol",     width=7)
        trade_table.add_column("Dir",        width=6)
        trade_table.add_column("Entry time", width=18)
        trade_table.add_column("Entry $",    width=10, justify="right")
        trade_table.add_column("Exit $",     width=10, justify="right")
        trade_table.add_column("Shares",     width=7,  justify="right")
        trade_table.add_column("P&L",        width=10, justify="right")
        trade_table.add_column("P&L %",      width=8,  justify="right")
        trade_table.add_column("Grade",      width=6)
        trade_table.add_column("Exit",       width=10)

        sorted_trades = sorted(result.closed_trades, key=lambda t: t.entry_time or datetime.min)
        for idx, t in enumerate(sorted_trades, 1):
            pnl_col = "green" if t.pnl > 0 else "red"
            dir_col = "green" if t.direction == "long" else "red"
            entry_ts = t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "—"
            trade_table.add_row(
                str(idx),
                f"[bold white]{t.symbol}[/bold white]",
                f"[{dir_col}]{t.direction.upper()}[/{dir_col}]",
                entry_ts,
                f"${t.entry_price:,.4f}",
                f"${t.exit_price:,.4f}" if t.exit_price else "—",
                str(t.shares),
                f"[{pnl_col}]${t.pnl:+,.2f}[/{pnl_col}]",
                f"[{pnl_col}]{t.pnl_pct*100:+.2f}%[/{pnl_col}]",
                t.grade,
                t.exit_reason or "—",
            )

        console.print(trade_table)

    console.print()
