"""Per-agent totals for the dashboard: every AI agent and research lane, by name and version.

An "agent" here is one strategy version in one trade style: the adaptive decision agent for scalping or swing,
or a research lane (one setup + variant). Totals come only from closed trades recorded in the chosen memory
(C virtual or D real); nothing is estimated. Running agents with no closed trade yet are listed with zero trades.
"""
from __future__ import annotations

import math
from collections import defaultdict

from ..domain import SimTrade
from ..engines.metrics import compute_metrics


def _setup_of(strategy_version: str) -> str:
    # research lane versions look like "rule-<setup>-<hash>"
    parts = strategy_version.split("-")
    return "-".join(parts[1:-1]) if len(parts) >= 3 and parts[0] == "rule" else strategy_version


def agent_name(style: str, strategy_version: str) -> str:
    if style == "research":
        return f"Research lane · {_setup_of(strategy_version).replace('_', ' ')}"
    return f"Adaptive AI agent · {style.capitalize()}"


def _row(style: str, version: str) -> dict:
    return {"agent": agent_name(style, version), "kind": "research lane" if style == "research" else "adaptive",
            "style": style, "version": version, "model_version": None, "brokers": [], "symbols": [],
            "running": False, "champion": False, "trades": 0, "wins": 0, "losses": 0, "win_rate": None,
            "net_profit": 0.0, "profit_factor": None, "max_drawdown": 0.0, "avg_r": None,
            "first_trade": None, "last_trade": None}


def leaderboard(trades: list[SimTrade], engines: list[dict] = (), lanes: list[dict] = ()) -> list[dict]:
    groups: dict[tuple[str, str], list[SimTrade]] = defaultdict(list)
    for t in trades:
        if t.exit_time is not None:
            groups[((t.context or {}).get("style", "scalp"), t.strategy_version)].append(t)
    rows: dict[tuple[str, str], dict] = {}
    for key, ts in groups.items():
        m = compute_metrics(ts)
        ts.sort(key=lambda t: t.exit_time)
        r = _row(*key)
        pf = m["profit_factor"]
        r.update(trades=m["total_trades"], wins=m["winning_trades"], losses=m["losing_trades"],
                 win_rate=m["win_rate"], net_profit=m["net_profit"], max_drawdown=m["max_drawdown"],
                 profit_factor=None if math.isinf(pf) else pf, no_losses=math.isinf(pf),
                 avg_r=m["avg_r_multiple"] if any(t.initial_risk_money > 0 for t in ts) else None,
                 brokers=sorted({t.broker for t in ts}), symbols=sorted({t.symbol for t in ts}),
                 first_trade=ts[0].entry_time.isoformat(), last_trade=ts[-1].exit_time.isoformat(),
                 model_version=next((t.model_version for t in reversed(ts) if t.model_version not in ("", "none")), None))
        rows[key] = r
    for st, style in [(e, e.get("style", "scalp")) for e in engines] + [(l, "research") for l in lanes]:
        key = (style, st.get("strategy_version") or "")
        r = rows.setdefault(key, _row(*key))
        r["running"] = True
        r["champion"] = r["champion"] or bool(st.get("champion"))
        if st.get("model_version"):
            r["model_version"] = st["model_version"]     # the live model, newer than the last closed trade
        for k, v in (("brokers", st.get("broker")), ("symbols", st.get("symbol"))):
            if v and v not in r[k]:
                r[k] = sorted([*r[k], v])
    return sorted(rows.values(), key=lambda r: (-r["running"], -r["trades"], r["agent"]))
