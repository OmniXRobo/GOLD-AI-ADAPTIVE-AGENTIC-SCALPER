"""Performance metrics computed from closed trades. No value is ever estimated or padded."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

from ..domain import SimTrade


def compute_metrics(trades: Iterable[SimTrade], starting_equity: float = 10_000.0) -> dict:
    ts = sorted((t for t in trades if t.exit_time is not None), key=lambda t: t.exit_time)
    n = len(ts)
    pnl = [t.net_pnl for t in ts]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    gp, gl = sum(wins), -sum(losses)
    eq = peak = starting_equity
    max_dd = max_dd_pct = 0.0
    for p in pnl:
        eq += p
        peak = max(peak, eq)
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd / peak * 100 if peak > 0 else 0.0
    rs = [t.r_multiple for t in ts if t.initial_risk_money > 0]
    sharpe = None
    if n >= 30:
        m = sum(pnl) / n
        sd = math.sqrt(sum((p - m) ** 2 for p in pnl) / (n - 1))
        sharpe = m / sd if sd > 0 else None
    monthly: dict[str, float] = defaultdict(float)
    regime: dict[str, dict] = defaultdict(lambda: {"trades": 0, "net": 0.0, "wins": 0})
    for t in ts:
        monthly[t.exit_time.strftime("%Y-%m")] += t.net_pnl
        r = regime[t.context.get("regime", "unknown")]
        r["trades"] += 1
        r["net"] += t.net_pnl
        r["wins"] += t.net_pnl > 0
    exits: dict[str, int] = defaultdict(int)
    for t in ts:
        exits[t.exit_reason.value if t.exit_reason else "open"] += 1
    return {
        "total_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": len(wins) / n if n else 0.0,
        "net_profit": sum(pnl),
        "gross_profit": gp,
        "gross_loss": gl,
        "profit_factor": (gp / gl) if gl > 0 else (math.inf if gp > 0 else 0.0),
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "avg_r_multiple": sum(rs) / len(rs) if rs else 0.0,
        "expectancy": sum(pnl) / n if n else 0.0,
        "sharpe_per_trade": sharpe,
        "total_commission": sum(t.commission for t in ts),
        "total_swap": sum(t.swap for t in ts),
        "total_spread_cost": sum(t.spread_cost for t in ts),
        "total_slippage_cost": sum(t.slippage_cost for t in ts),
        "monthly": dict(monthly),
        "by_regime": {k: dict(v) for k, v in regime.items()},
        "exit_reasons": dict(exits),
        "ending_equity": starting_equity + sum(pnl),
    }


def json_safe(m: dict) -> dict:
    """Replace inf/nan so metrics serialize to JSON."""
    out = {}
    for k, v in m.items():
        if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
            out[k] = None if math.isnan(v) else "inf"
        elif isinstance(v, dict):
            out[k] = json_safe(v)
        else:
            out[k] = v
    return out
