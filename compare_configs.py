"""
Compares grade filter configurations over the same 30-day window.
Run: python compare_configs.py
"""
from live_backtest import run_live_backtest, print_live_backtest_report

START = "2026-02-18"
END   = "2026-03-19"
CAP   = 100_000.0
TF    = "1Min"
SYMS  = ["SLV", "USO", "GDX", "XLE", "UNG", "IWM", "SPY", "QQQ"]

print("\n========== CONFIG A: All grades (C+) ==========")
rC = run_live_backtest(
    symbols=SYMS,
    start_date=START, end_date=END,
    initial_capital=CAP, timeframe=TF,
    min_grade="C",
)
print_live_backtest_report(rC)

print("\n========== CONFIG B: Grade B and above only ==========")
rB = run_live_backtest(
    symbols=SYMS,
    start_date=START, end_date=END,
    initial_capital=CAP, timeframe=TF,
    min_grade="B",
)
print_live_backtest_report(rB)

print()
print("=" * 65)
print("SIDE-BY-SIDE COMPARISON")
print("=" * 65)
fmt = "  {label:<22}  PnL={pnl:>+10,.2f}  Return={ret:>+6.2f}%  WR={wr:.1f}%  DD={dd:.2f}%  Trades={n:>3}  Sharpe={sh}"
for label, r in [("All grades (C+)", rC), ("Grade B+ only", rB)]:
    sh = f"{r.sharpe_ratio:.2f}" if r.sharpe_ratio == r.sharpe_ratio else "N/A"
    print(fmt.format(
        label=label,
        pnl=r.total_pnl, ret=r.total_return_pct * 100,
        wr=r.win_rate * 100, dd=r.max_drawdown_pct * 100,
        n=len(r.closed_trades), sh=sh,
    ))

print()
c_only_trades = [t for t in rC.closed_trades if t.grade == "C"]
c_pnl  = sum(t.pnl for t in c_only_trades)
c_wins = sum(1 for t in c_only_trades if t.pnl > 0)
print(f"  Grade C trades in isolation: {len(c_only_trades)} trades, "
      f"{c_wins}/{len(c_only_trades)} wins "
      f"({c_wins/len(c_only_trades)*100:.1f}% WR), "
      f"net P&L = ${c_pnl:+,.2f}")
print()
winner = "Grade B+ only" if rB.total_pnl > rC.total_pnl else "All grades (C+)"
print(f"  Winner on P&L: {winner}")
