"""
Rich terminal dashboard for the trading bot.

Displays:
  - Strategy signals panel with confirmation status
  - Config panel (current settings)
  - Recent decisions / P&L summary
  - Live status bar
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

import config

_ET = ZoneInfo("America/New_York")

logger = logging.getLogger(__name__)
console = Console()


# ─── Colour helpers ───────────────────────────────────────────────────────────

_GRADE_COLOUR = {"A": "bright_green", "B": "green", "C": "yellow", "F": "dim"}
_VOTE_CONFIRM_COLOUR = "green"
_VOTE_ABSTAIN_COLOUR = "white dim"
_VOTE_CONFLICT_COLOUR = "red"


def _grade_text(grade: str) -> Text:
    colour = _GRADE_COLOUR.get(grade, "white")
    return Text(grade, style=colour)


def _vote_cell(vote: str, direction: str) -> Text:
    """
    Render a single strategy vote cell.
    vote:      "buy" | "sell" | "abstain"
    direction: the overall confirmed direction ("buy" | "sell" | "no_trade")
    """
    if vote == "abstain":
        return Text("NEUT ✗", style=_VOTE_ABSTAIN_COLOUR)
    if direction == "no_trade":
        label = vote.upper()
        return Text(f"{label} ✗", style=_VOTE_ABSTAIN_COLOUR)

    aligns = (vote == "buy" and direction == "buy") or (vote == "sell" and direction == "sell")
    if aligns:
        return Text(f"{vote.upper()} ✓", style=_VOTE_CONFIRM_COLOUR)
    else:
        return Text(f"{vote.upper()} ✗", style=_VOTE_CONFLICT_COLOUR)


# ─── Signals table ────────────────────────────────────────────────────────────

def build_signals_table(symbol_reports: list[dict]) -> Table:
    """
    symbol_reports: list of dicts, each with keys:
        symbol, macd_vote, vwap_vote, ema_vote, pa_vote,
        confirmed, grade, direction, signal_count, confirmation_report
    """
    table = Table(
        title="Strategy Signal Confirmation",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Symbol",    style="bold white", no_wrap=True, width=8)
    table.add_column("MACD",      width=10)
    table.add_column("VWAP",      width=10)
    table.add_column("EMA",       width=10)
    table.add_column("PriceAct",  width=10)
    table.add_column("Confirmed", width=12)
    table.add_column("Grade",     width=7)
    table.add_column("Direction", width=12)

    for r in symbol_reports:
        report = r.get("confirmation_report", {})
        direction = report.get("direction", "no_trade")
        votes_list = report.get("votes", [])
        votes_by_name = {v["strategy"]: v["vote"] for v in votes_list}

        macd_vote = votes_by_name.get("macd", "abstain")
        vwap_vote = votes_by_name.get("vwap", "abstain")
        ema_vote = votes_by_name.get("ema_cross", "abstain")
        pa_vote = votes_by_name.get("price_action", "abstain")

        confirmed = report.get("confirmed", False)
        grade = report.get("quality", "F")
        signal_count = report.get("signal_count", "0/4")

        if confirmed and direction == "buy":
            dir_text = Text("LONG ★" if signal_count == "4/4" else "LONG", style="green")
        elif confirmed and direction == "sell":
            dir_text = Text("SHORT ★" if signal_count == "4/4" else "SHORT", style="red")
        else:
            dir_text = Text("—", style="dim")

        confirmed_cell = Text(
            f"{signal_count} {'YES' if confirmed else 'NO'}",
            style="green bold" if confirmed else "dim",
        )

        table.add_row(
            r.get("symbol", "?"),
            _vote_cell(macd_vote, direction),
            _vote_cell(vwap_vote, direction),
            _vote_cell(ema_vote, direction),
            _vote_cell(pa_vote, direction),
            confirmed_cell,
            _grade_text(grade),
            dir_text,
        )

    return table


# ─── Config panel ─────────────────────────────────────────────────────────────

def build_config_panel() -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 2))
    t.add_column("Key",   style="cyan", no_wrap=True)
    t.add_column("Value", style="white")

    shorts_text = Text(
        "enabled" if config.ALLOW_SHORTS else "disabled",
        style="green" if config.ALLOW_SHORTS else "red",
    )
    mode_style = "bright_green" if config.CONFIRMATION_MODE == "strict" else "yellow"

    t.add_row("MIN_SIGNALS_REQUIRED", f"{config.MIN_SIGNALS_REQUIRED}/4")
    t.add_row("MIN_SIGNAL_STRENGTH",  f"{config.MIN_SIGNAL_STRENGTH:.2f}")
    t.add_row("CONFIRMATION_MODE",    Text(config.CONFIRMATION_MODE.upper(), style=mode_style))
    t.add_row("SHORTS",               shorts_text)
    t.add_row("MAX_POSITION_SIZE",    f"{config.MAX_POSITION_SIZE*100:.0f}%")
    t.add_row("MAX_POSITIONS",        str(config.MAX_OPEN_POSITIONS))
    t.add_row("WATCHLIST",            ", ".join(config.WATCHLIST))

    return Panel(t, title="[bold cyan]Configuration[/bold cyan]", box=box.ROUNDED)


# ─── Stats panel ──────────────────────────────────────────────────────────────

def build_stats_panel(stats: Optional[dict]) -> Panel:
    if not stats:
        return Panel(
            Text("No trade history yet.", style="dim"),
            title="[bold cyan]Confirmation Stats[/bold cyan]",
            box=box.ROUNDED,
        )

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    t.add_column("Grade",    width=8)
    t.add_column("Trades",   width=8, justify="right")
    t.add_column("Wins",     width=6, justify="right")
    t.add_column("Win%",     width=8, justify="right")
    t.add_column("Avg P&L",  width=10, justify="right")

    grade_order = [("A", "A_grade"), ("B", "B_grade"), ("C", "C_grade"), ("Override", "overrides")]
    for label, key in grade_order:
        data = stats.get(key, {})
        trades = data.get("trades", 0)
        if trades == 0:
            continue
        wins = data.get("wins", 0)
        win_rate = data.get("win_rate", 0.0)
        avg_pnl = data.get("avg_pnl", 0.0)
        wr_colour = "green" if win_rate >= 0.55 else ("yellow" if win_rate >= 0.4 else "red")
        pnl_colour = "green" if avg_pnl > 0 else "red"
        t.add_row(
            label,
            str(trades),
            str(wins),
            Text(f"{win_rate*100:.1f}%", style=wr_colour),
            Text(f"${avg_pnl:+.2f}", style=pnl_colour),
        )

    total = stats.get("total_trades", 0)
    wr = stats.get("overall_win_rate", 0.0)
    footer = Text(
        f"Total trades: {total}  |  Overall win rate: {wr*100:.1f}%",
        style="cyan",
    )

    grid = Table.grid(padding=1)
    grid.add_row(t, footer)
    return Panel(
        grid,
        title="[bold cyan]Confirmation Stats[/bold cyan]",
        box=box.ROUNDED,
    )


# ─── Market clock ────────────────────────────────────────────────────────────

def _fmt_duration(seconds: int) -> str:
    """Format a duration in seconds as Xh Ym Zs."""
    seconds = abs(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def build_market_clock() -> Panel:
    """
    Shows time until market open (when closed) or time market has been open
    (when open). Updates every second via the Live refresh rate.
    """
    now_et = datetime.now(_ET)
    weekday = now_et.weekday()  # 0=Mon, 6=Sun

    open_time  = now_et.replace(
        hour=config.MARKET_OPEN_HOUR, minute=config.MARKET_OPEN_MINUTE,
        second=0, microsecond=0,
    )
    close_time = now_et.replace(
        hour=config.MARKET_CLOSE_HOUR, minute=config.MARKET_CLOSE_MINUTE,
        second=0, microsecond=0,
    )

    t = Table(box=None, show_header=False, padding=(0, 3))
    t.add_column("Label", style="cyan",  no_wrap=True)
    t.add_column("Value", style="white", no_wrap=True)
    t.add_column("Extra", style="dim",   no_wrap=True)

    now_str = now_et.strftime("%I:%M:%S %p ET  %a %b %d")
    t.add_row("Current time", now_str, "")

    if weekday >= 5:
        # Weekend
        days_until_monday = 7 - weekday  # 2 for Sat, 1 for Sun
        next_open = (now_et + timedelta(days=days_until_monday)).replace(
            hour=config.MARKET_OPEN_HOUR, minute=config.MARKET_OPEN_MINUTE,
            second=0, microsecond=0,
        )
        secs = int((next_open - now_et).total_seconds())
        t.add_row(
            "Market status",
            "[red]CLOSED (weekend)[/red]",
            "",
        )
        t.add_row(
            "Opens Monday in",
            f"[yellow]{_fmt_duration(secs)}[/yellow]",
            f"at {open_time.strftime('%I:%M %p ET')}",
        )
    elif now_et < open_time:
        # Pre-market
        secs = int((open_time - now_et).total_seconds())
        t.add_row(
            "Market status",
            "[yellow]CLOSED (pre-market)[/yellow]",
            "",
        )
        t.add_row(
            "Opens in",
            f"[yellow]{_fmt_duration(secs)}[/yellow]",
            f"at {open_time.strftime('%I:%M %p ET')}",
        )
    elif now_et <= close_time:
        # Market open
        secs_open  = int((now_et - open_time).total_seconds())
        secs_close = int((close_time - now_et).total_seconds())
        t.add_row(
            "Market status",
            "[bright_green]OPEN[/bright_green]",
            "",
        )
        t.add_row(
            "Open for",
            f"[green]{_fmt_duration(secs_open)}[/green]",
            f"closes in {_fmt_duration(secs_close)}",
        )
    else:
        # After hours
        tomorrow = now_et + timedelta(days=1)
        # Skip to Monday if Friday after close
        if tomorrow.weekday() >= 5:
            days_ahead = 7 - tomorrow.weekday()
            tomorrow = tomorrow + timedelta(days=days_ahead)
        next_open = tomorrow.replace(
            hour=config.MARKET_OPEN_HOUR, minute=config.MARKET_OPEN_MINUTE,
            second=0, microsecond=0,
        )
        secs = int((next_open - now_et).total_seconds())
        t.add_row(
            "Market status",
            "[red]CLOSED (after-hours)[/red]",
            "",
        )
        t.add_row(
            "Opens tomorrow in",
            f"[yellow]{_fmt_duration(secs)}[/yellow]",
            f"at {open_time.strftime('%I:%M %p ET')}",
        )

    return Panel(t, title="[bold cyan]Market Clock[/bold cyan]", box=box.ROUNDED)


# ─── Status bar ──────────────────────────────────────────────────────────────

def build_status_bar(status: str, last_scan: Optional[datetime] = None) -> Text:
    ts = last_scan.strftime("%H:%M:%S") if last_scan else "--:--:--"
    return Text(f" {ts}  {status}", style="bold white on dark_blue")


# ─── Full live dashboard ──────────────────────────────────────────────────────

def render_snapshot(
    symbol_reports: list[dict],
    stats: Optional[dict] = None,
    status: str = "Running",
    last_scan: Optional[datetime] = None,
) -> None:
    """
    Print a single static snapshot of the dashboard to the terminal.
    Use for --confirm-test mode or one-shot prints.
    """
    console.print(build_config_panel())
    console.print(build_signals_table(symbol_reports))
    if stats:
        console.print(build_stats_panel(stats))
    console.print(build_status_bar(status, last_scan))


class LiveDashboard:
    """
    Context-manager wrapper around Rich Live for continuous updates.

    Usage:
        with LiveDashboard() as dash:
            while True:
                dash.update(symbol_reports, stats, status)
                time.sleep(60)
    """

    def __init__(self, refresh_per_second: float = 1.0) -> None:
        self._refresh = refresh_per_second
        self._live: Optional[Live] = None
        self._symbol_reports: list[dict] = []
        self._stats: Optional[dict] = None
        self._status = "Starting…"
        self._last_scan: Optional[datetime] = None

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="top", size=5),
            Layout(build_config_panel(), name="config", size=10),
            Layout(build_signals_table(self._symbol_reports), name="signals"),
            Layout(build_stats_panel(self._stats), name="stats", size=10),
            Layout(build_status_bar(self._status, self._last_scan), name="status", size=1),
        )
        layout["top"].update(build_market_clock())
        return layout

    def update(
        self,
        symbol_reports: list[dict],
        stats: Optional[dict] = None,
        status: str = "Running",
        last_scan: Optional[datetime] = None,
    ) -> None:
        self._symbol_reports = symbol_reports
        self._stats = stats
        self._status = status
        self._last_scan = last_scan or datetime.now()
        if self._live:
            self._live.update(self._build_layout())

    def __enter__(self) -> "LiveDashboard":
        self._live = Live(
            self._build_layout(),
            console=console,
            refresh_per_second=self._refresh,
            screen=False,
            vertical_overflow="visible",
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args) -> None:
        if self._live:
            self._live.__exit__(*args)
