"""
Backtester — replay historical bars through all four strategies and the
confirmation engine to simulate how the bot would have performed.

Usage (via main.py):
    python main.py --backtest --symbol AAPL
    python main.py --backtest --symbol AAPL --start 2024-01-01 --end 2024-12-31
    python main.py --backtest --symbol AAPL --start 2024-06-01 --mode weighted
    python main.py --backtest --symbol USO,GLD,UNG --start 2024-01-01

No real orders are ever submitted. Everything is simulated.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
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
console = Console()

# Minimum bars needed before the first signal can fire (driven by EMA_SLOW setting)
WARMUP_BARS = config.EMA_SLOW + 10


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class SimTrade:
    symbol: str
    direction: str          # "long" | "short"
    entry_bar: int
    entry_time: datetime
    entry_price: float
    stop_price: float
    target_price: float
    shares: int
    grade: str
    signal_count: str
    confirmed: bool

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
class BacktestResult:
    symbol: str
    start_date: str
    end_date: str
    timeframe: str
    total_bars: int
    warmup_bars: int
    mode: str
    min_required: int
    min_strength: float
    initial_capital: float
    trades: list[SimTrade] = field(default_factory=list)

    # computed on finalise()
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    equity_curve: list[float] = field(default_factory=list)

    def finalise(self) -> None:
        self._compute_equity_curve()
        self._compute_drawdown()
        self._compute_sharpe()

    # ── Aggregate helpers ────────────────────────────────────────────────────

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

    def _compute_equity_curve(self) -> None:
        capital = self.initial_capital
        curve = [capital]
        for t in self.closed_trades:
            capital += t.pnl
            curve.append(capital)
        self.equity_curve = curve
        self.total_return_pct = (capital - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0.0

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
        # annualise assuming ~252 trading days of ~6.5h each = ~1638 hourly bars
        annualisation = math.sqrt(1638)
        daily_rf = risk_free_rate / 252
        # Use a minimum std threshold to avoid near-zero division producing garbage values
        if std_r < 1e-8:
            self.sharpe_ratio = float("nan")
        else:
            self.sharpe_ratio = (mean_r - daily_rf) / std_r * annualisation


# ─── Data fetching ────────────────────────────────────────────────────────────

def fetch_historical_bars(
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe: str = "1Hour",
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
        feed=DataFeed.IEX,   # IEX feed — free on all Alpaca accounts
    )
    bars = client.get_stock_bars(req)
    df = bars.df

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level=0)

    df = df.rename(columns=str.lower)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    return df


# ─── Simulation helpers ───────────────────────────────────────────────────────

def _calculate_shares(capital: float, price: float, max_position_pct: float = None) -> int:
    pct = max_position_pct or config.MAX_POSITION_SIZE
    dollars = capital * pct
    return max(int(dollars / price), 1)


def _check_exits(trade: SimTrade, bar: pd.Series, bar_idx: int) -> Optional[str]:
    """
    Check if the current bar triggered a stop or target for an open trade.
    Uses the bar's high/low to determine if levels were hit intra-bar.
    """
    if trade.direction == "long":
        if bar["low"] <= trade.stop_price:
            trade.exit_price = trade.stop_price
            trade.exit_reason = "stop"
            trade.exit_bar = bar_idx
            trade.exit_time = bar.name
            return "stop"
        if bar["high"] >= trade.target_price:
            trade.exit_price = trade.target_price
            trade.exit_reason = "target"
            trade.exit_bar = bar_idx
            trade.exit_time = bar.name
            return "target"
    else:  # short
        if bar["high"] >= trade.stop_price:
            trade.exit_price = trade.stop_price
            trade.exit_reason = "stop"
            trade.exit_bar = bar_idx
            trade.exit_time = bar.name
            return "stop"
        if bar["low"] <= trade.target_price:
            trade.exit_price = trade.target_price
            trade.exit_reason = "target"
            trade.exit_bar = bar_idx
            trade.exit_time = bar.name
            return "target"
    return None


# ─── Main backtest runner ─────────────────────────────────────────────────────

def run_backtest(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timeframe: str = "1Hour",
    initial_capital: float = 30_000.0,
    min_required: Optional[int] = None,
    min_strength: Optional[float] = None,
    mode: Optional[str] = None,
    allow_shorts: Optional[bool] = None,
    stop_loss_pct: Optional[float] = None,
    take_profit_pct: Optional[float] = None,
    max_position_pct: Optional[float] = None,
) -> BacktestResult:
    """
    Run a full backtest for one symbol. Returns a BacktestResult.
    """
    # Settings (fall back to config)
    _min_required = min_required if min_required is not None else config.MIN_SIGNALS_REQUIRED
    _min_strength = min_strength if min_strength is not None else config.MIN_SIGNAL_STRENGTH
    _mode = mode or config.CONFIRMATION_MODE
    _allow_shorts = allow_shorts if allow_shorts is not None else config.ALLOW_SHORTS
    _stop_pct = stop_loss_pct or config.STOP_LOSS_PCT
    _target_pct = take_profit_pct or config.TAKE_PROFIT_PCT
    _max_pos = max_position_pct or config.MAX_POSITION_SIZE

    # Date range
    tz = timezone.utc
    end_dt = datetime.now(tz) - timedelta(hours=1) if not end_date else datetime.fromisoformat(end_date).replace(tzinfo=tz)
    if start_date:
        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=tz)
    else:
        start_dt = end_dt - timedelta(days=180)

    # Fetch with extra warmup data prepended
    warmup_start = start_dt - timedelta(days=60)
    console.print(f"  Fetching {symbol} bars {start_dt.date()} -> {end_dt.date()} ...")

    try:
        df = fetch_historical_bars(symbol, warmup_start, end_dt, timeframe)
    except Exception as exc:
        console.print(f"  [red]Failed to fetch data for {symbol}: {exc}[/red]")
        raise

    if df.empty:
        raise ValueError(f"No data returned for {symbol}")

    console.print(f"  Got {len(df)} total bars (including warmup)")

    # Find the index where the actual backtest window starts
    start_ts = pd.Timestamp(start_dt)
    backtest_start_idx = df.index.searchsorted(start_ts)
    # Ensure at least WARMUP_BARS before the first live bar
    backtest_start_idx = max(backtest_start_idx, WARMUP_BARS)

    result = BacktestResult(
        symbol=symbol,
        start_date=str(start_dt.date()),
        end_date=str(end_dt.date()),
        timeframe=timeframe,
        total_bars=len(df) - backtest_start_idx,
        warmup_bars=backtest_start_idx,
        mode=_mode,
        min_required=_min_required,
        min_strength=_min_strength,
        initial_capital=initial_capital,
    )

    capital = initial_capital
    open_trade: Optional[SimTrade] = None

    for i in range(backtest_start_idx, len(df)):
        bar = df.iloc[i]

        # 1. Check exits for any open trade — skip the entry bar itself to avoid
        #    immediately triggering stop/target on the bar the trade was entered
        if open_trade is not None and i > open_trade.entry_bar:
            exit_reason = _check_exits(open_trade, bar, i)
            if exit_reason:
                capital += open_trade.pnl
                open_trade = None

        # 2. Only look for new entries when flat
        if open_trade is not None:
            continue

        # 3. Run strategies on window up to (not including) current bar
        window = df.iloc[: i + 1]

        try:
            macd_sig = get_macd_signal(window)
            vwap_sig = get_vwap_signal(window)
            ema_sig = get_ema_signal(window)
            pa_sig = get_price_action_signal(window)
        except Exception as exc:
            log.debug("Strategy error at bar %d: %s", i, exc)
            continue

        report = evaluate_confirmation(
            macd_signal=macd_sig,
            vwap_signal=vwap_sig,
            ema_signal=ema_sig,
            price_action_signal=pa_sig,
            min_required=_min_required,
            min_strength=_min_strength,
            mode=_mode,
            allow_shorts=_allow_shorts,
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

        # 4. Simulate entry at the NEXT bar's open (avoid lookahead bias)
        if i + 1 >= len(df):
            continue
        next_bar = df.iloc[i + 1]
        entry_price = float(next_bar["open"])

        shares = _calculate_shares(capital, entry_price, _max_pos)

        if direction == "long":
            stop_price = round(entry_price * (1 - _stop_pct), 4)
            target_price = round(entry_price * (1 + _target_pct), 4)
        else:
            stop_price = round(entry_price * (1 + _stop_pct), 4)
            target_price = round(entry_price * (1 - _target_pct), 4)

        open_trade = SimTrade(
            symbol=symbol,
            direction="long" if direction == "buy" else "short",
            entry_bar=i + 1,
            entry_time=next_bar.name,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            shares=shares,
            grade=report["quality"],
            signal_count=report["signal_count"],
            confirmed=True,
        )
        result.trades.append(open_trade)

    # Close any trade still open at end of data
    if open_trade is not None and not df.empty:
        last_bar = df.iloc[-1]
        open_trade.exit_price = float(last_bar["close"])
        open_trade.exit_reason = "end_of_data"
        open_trade.exit_bar = len(df) - 1
        open_trade.exit_time = last_bar.name
        capital += open_trade.pnl
        open_trade = None

    result.finalise()
    return result


# ─── Report renderer ──────────────────────────────────────────────────────────

def _grade_row(result: BacktestResult, grade: str) -> Optional[tuple]:
    trades = result.trades_by_grade(grade)
    if not trades:
        return None
    wins = [t for t in trades if t.pnl > 0]
    total_pnl = sum(t.pnl for t in trades)
    win_rate = len(wins) / len(trades)
    wr_colour = "green" if win_rate >= 0.55 else ("yellow" if win_rate >= 0.4 else "red")
    pnl_colour = "green" if total_pnl > 0 else "red"
    return (
        grade,
        str(len(trades)),
        str(len(wins)),
        (f"{win_rate*100:.1f}%", wr_colour),
        (f"${total_pnl:+,.2f}", pnl_colour),
    )


def print_backtest_report(result: BacktestResult) -> None:
    console.print()
    console.print(Rule(f"[bold cyan]BACKTEST REPORT — {result.symbol}[/bold cyan]"))

    # ── Summary panel ────────────────────────────────────────────────────────
    n = len(result.closed_trades)
    ret_colour = "green" if result.total_return_pct >= 0 else "red"
    dd_colour = "green" if result.max_drawdown_pct < 0.05 else ("yellow" if result.max_drawdown_pct < 0.15 else "red")
    sharpe_valid = not math.isnan(result.sharpe_ratio)
    sharpe_colour = "green" if sharpe_valid and result.sharpe_ratio >= 1.0 else ("yellow" if sharpe_valid and result.sharpe_ratio >= 0.5 else "dim")
    sharpe_display = f"{result.sharpe_ratio:.2f}" if sharpe_valid else "N/A (insufficient variance)"
    wr_colour = "green" if result.win_rate >= 0.55 else ("yellow" if result.win_rate >= 0.45 else "red")
    pf_colour = "green" if result.profit_factor >= 1.5 else ("yellow" if result.profit_factor >= 1.0 else "red")

    summary = Table(box=None, show_header=False, padding=(0, 3))
    summary.add_column("Key",   style="cyan", no_wrap=True)
    summary.add_column("Value", style="white")
    summary.add_column("Key2",  style="cyan", no_wrap=True)
    summary.add_column("Value2", style="white")

    summary.add_row("Period",        f"{result.start_date}  ->  {result.end_date}",
                    "Timeframe",     result.timeframe)
    summary.add_row("Total bars",    f"{result.total_bars:,}  (warmup: {result.warmup_bars})",
                    "Mode",          f"{result.mode}  (min {result.min_required}/4, strength >= {result.min_strength})")
    summary.add_row("Initial capital", f"${result.initial_capital:,.2f}",
                    "Final capital",   f"${result.initial_capital + result.total_pnl:,.2f}")
    summary.add_row("Total return",  f"[{ret_colour}]{result.total_return_pct*100:+.2f}%[/{ret_colour}]",
                    "Total P&L",     f"[{ret_colour}]${result.total_pnl:+,.2f}[/{ret_colour}]")
    summary.add_row("Max drawdown",  f"[{dd_colour}]{result.max_drawdown_pct*100:.2f}%[/{dd_colour}]",
                    "Sharpe ratio",  f"[{sharpe_colour}]{sharpe_display}[/{sharpe_colour}]")
    summary.add_row("Total trades",  str(n),
                    "Avg hold",      f"{result.avg_hold_bars:.1f} bars")
    summary.add_row("Win rate",      f"[{wr_colour}]{result.win_rate*100:.1f}%[/{wr_colour}]",
                    "Profit factor", f"[{pf_colour}]{result.profit_factor:.2f}[/{pf_colour}]")
    summary.add_row("Avg win",       f"[green]${result.avg_win:+,.2f}[/green]",
                    "Avg loss",      f"[red]${result.avg_loss:+,.2f}[/red]")

    console.print(Panel(summary, title="[bold]Summary[/bold]", box=box.ROUNDED))

    # ── By grade table ────────────────────────────────────────────────────────
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
        row = _grade_row(result, grade)
        if row:
            wr_val, wr_col = row[3]
            pnl_val, pnl_col = row[4]
            grade_table.add_row(
                row[0], row[1], row[2],
                f"[{wr_col}]{wr_val}[/{wr_col}]",
                f"[{pnl_col}]{pnl_val}[/{pnl_col}]",
            )

    console.print(grade_table)

    # ── Exit reason breakdown ─────────────────────────────────────────────────
    stops   = [t for t in result.closed_trades if t.exit_reason == "stop"]
    targets = [t for t in result.closed_trades if t.exit_reason == "target"]
    eod     = [t for t in result.closed_trades if t.exit_reason == "end_of_data"]

    exit_table = Table(title="Exit Breakdown", box=box.ROUNDED, header_style="bold cyan")
    exit_table.add_column("Exit reason",  width=16)
    exit_table.add_column("Count",        width=8, justify="right")
    exit_table.add_column("Avg P&L",      width=12, justify="right")

    for label, group, colour in [
        ("Target hit",    targets, "green"),
        ("Stop hit",      stops,   "red"),
        ("End of data",   eod,     "dim"),
    ]:
        if group:
            avg = sum(t.pnl for t in group) / len(group)
            exit_table.add_row(label, str(len(group)), f"[{colour}]${avg:+,.2f}[/{colour}]")

    console.print(exit_table)

    # ── Individual trades ─────────────────────────────────────────────────────
    if result.closed_trades:
        trade_table = Table(
            title="All Trades",
            box=box.SIMPLE,
            header_style="bold cyan",
            show_lines=False,
        )
        trade_table.add_column("#",        width=4,  justify="right")
        trade_table.add_column("Dir",      width=6)
        trade_table.add_column("Entry time",  width=18)
        trade_table.add_column("Entry $",  width=10, justify="right")
        trade_table.add_column("Exit $",   width=10, justify="right")
        trade_table.add_column("Shares",   width=7,  justify="right")
        trade_table.add_column("P&L",      width=10, justify="right")
        trade_table.add_column("P&L %",    width=8,  justify="right")
        trade_table.add_column("Grade",    width=6)
        trade_table.add_column("Exit",     width=10)

        for idx, t in enumerate(result.closed_trades, 1):
            pnl_col = "green" if t.pnl > 0 else "red"
            dir_col = "green" if t.direction == "long" else "red"
            entry_ts = t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "—"
            trade_table.add_row(
                str(idx),
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


# ─── Multi-symbol summary ─────────────────────────────────────────────────────

def print_multi_summary(results: list[BacktestResult]) -> None:
    """Print a combined summary box after all individual reports."""
    if not results:
        return

    console.print()
    console.print(Rule("[bold bright_cyan]BACKTEST COMPLETE — OVERALL SUMMARY[/bold bright_cyan]"))

    # Totals across all symbols
    total_pnl        = sum(r.total_pnl for r in results)
    total_trades     = sum(len(r.closed_trades) for r in results)
    total_wins       = sum(len(r.win_trades)    for r in results)
    total_capital    = sum(r.initial_capital    for r in results)
    overall_wr       = total_wins / total_trades if total_trades > 0 else 0.0
    overall_return   = total_pnl / total_capital if total_capital > 0 else 0.0

    pnl_colour    = "green" if total_pnl    >= 0 else "red"
    ret_colour    = "green" if overall_return >= 0 else "red"
    wr_colour     = "green" if overall_wr   >= 0.55 else ("yellow" if overall_wr >= 0.45 else "red")

    totals = Table(box=None, show_header=False, padding=(0, 4))
    totals.add_column("Key",   style="cyan",  no_wrap=True)
    totals.add_column("Value", style="white")
    totals.add_column("Key2",  style="cyan",  no_wrap=True)
    totals.add_column("Value2", style="white")

    totals.add_row(
        "Symbols tested",  str(len(results)),
        "Total trades",    str(total_trades),
    )
    totals.add_row(
        "Combined capital", f"${total_capital:,.2f}",
        "Overall win rate", f"[{wr_colour}]{overall_wr*100:.1f}%[/{wr_colour}]",
    )
    totals.add_row(
        "Total P&L",
        f"[{pnl_colour}]${total_pnl:+,.2f}[/{pnl_colour}]",
        "Total return",
        f"[{ret_colour}]{overall_return*100:+.2f}%[/{ret_colour}]",
    )

    console.print(Panel(totals, title="[bold]Combined Results[/bold]", box=box.DOUBLE_EDGE))

    # ── Ranked table ──────────────────────────────────────────────────────────
    ranked = sorted(results, key=lambda r: r.total_pnl, reverse=True)

    rank_table = Table(
        title="Symbols Ranked by Profitability",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=False,
    )
    rank_table.add_column("#",          width=4,  justify="right")
    rank_table.add_column("Symbol",     width=8)
    rank_table.add_column("Total P&L",  width=12, justify="right")
    rank_table.add_column("Return %",   width=10, justify="right")
    rank_table.add_column("Trades",     width=8,  justify="right")
    rank_table.add_column("Win %",      width=8,  justify="right")
    rank_table.add_column("Avg hold",   width=10, justify="right")
    rank_table.add_column("Best grade", width=10)
    rank_table.add_column("Verdict",    width=18)

    for pos, r in enumerate(ranked, 1):
        pnl_col = "green" if r.total_pnl >= 0 else "red"
        ret_col = "green" if r.total_return_pct >= 0 else "red"
        wr      = r.win_rate
        wr_col  = "green" if wr >= 0.55 else ("yellow" if wr >= 0.45 else "red")

        # Best grade achieved
        for g in ("A", "B", "C"):
            if r.trades_by_grade(g):
                best_grade = g
                break
        else:
            best_grade = "—"

        grade_col = {"A": "bright_green", "B": "green", "C": "yellow"}.get(best_grade, "dim")

        # Simple verdict
        n = len(r.closed_trades)
        if n == 0:
            verdict = "[dim]no trades[/dim]"
        elif r.total_pnl > 0 and wr >= 0.55:
            verdict = "[bright_green]Strong[/bright_green]"
        elif r.total_pnl > 0 and wr >= 0.45:
            verdict = "[green]Profitable[/green]"
        elif r.total_pnl > 0:
            verdict = "[yellow]Marginal[/yellow]"
        elif r.total_pnl < 0 and wr < 0.4:
            verdict = "[red]Avoid[/red]"
        else:
            verdict = "[red]Losing[/red]"

        rank_table.add_row(
            str(pos),
            f"[bold white]{r.symbol}[/bold white]",
            f"[{pnl_col}]${r.total_pnl:+,.2f}[/{pnl_col}]",
            f"[{ret_col}]{r.total_return_pct*100:+.2f}%[/{ret_col}]",
            str(n),
            f"[{wr_col}]{wr*100:.1f}%[/{wr_col}]",
            f"{r.avg_hold_bars:.1f} bars",
            f"[{grade_col}]{best_grade}[/{grade_col}]",
            verdict,
        )

    console.print(rank_table)
    console.print()


# ─── Multi-symbol runner ──────────────────────────────────────────────────────

def run_backtest_multi(
    symbols: list[str],
    **kwargs,
) -> list[BacktestResult]:
    results = []
    for symbol in symbols:
        console.print(f"\n[bold cyan]Running backtest for {symbol}...[/bold cyan]")
        try:
            result = run_backtest(symbol, **kwargs)
            print_backtest_report(result)
            results.append(result)
        except Exception as exc:
            console.print(f"[red]Backtest failed for {symbol}: {exc}[/red]")

    print_multi_summary(results)
    return results
