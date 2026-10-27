"""Profit alerts: trades that closed with a positive net result, for the dashboard and the phone app.

Alerts are read straight from the trade memories, so they show only trades the engines actually recorded:
Memory C (live virtual, estimated fills) and Memory D (actual broker fills). Every alert says which one it is.
Backtest and walk-forward trades (Memories A and B) never raise an alert. Reading alerts places no order.
"""
from __future__ import annotations

from datetime import datetime

from ..agents.decision import STYLE_LABELS
from ..domain import MemoryDomain, Side, SimTrade
from ..instruments import instrument_for
from ..memory.store import MemoryStore

ALERT_DOMAINS = (MemoryDomain.VIRTUAL, MemoryDomain.REAL)
ACCOUNT_LABELS = {MemoryDomain.VIRTUAL: "Virtual (estimated fills)", MemoryDomain.REAL: "Real (broker fill)"}


def is_exploration(t: SimTrade) -> bool:
    return bool(t.context.get("exploration")) or "[EXPLORATION]" in t.explanation


def profit_alert(domain: MemoryDomain, t: SimTrade) -> dict:
    inst = instrument_for(t.symbol)
    digits = inst.display_digits if inst else 2
    pips = None
    if inst and t.exit_price is not None:
        move = t.exit_price - t.entry_price
        pips = round((move if t.side == Side.BUY else -move) / inst.pip_size, 1)
    style = t.context.get("style", "scalp")
    return {
        # Domain is part of the id, so a virtual and a real trade can never share one alert.
        "id": f"{domain.value}:{t.trade_id}", "trade_id": t.trade_id, "account": domain.value,
        "account_label": ACCOUNT_LABELS[domain], "simulated": domain != MemoryDomain.REAL,
        "broker": t.broker, "symbol": t.symbol, "instrument": inst.name if inst else t.symbol, "digits": digits,
        "side": t.side.value, "style": style, "style_label": STYLE_LABELS.get(style, style.capitalize()),
        "lots": t.lots,
        "entry_price": t.entry_price, "exit_price": t.exit_price,
        "entry_time": t.entry_time.isoformat(), "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "exit_reason": t.exit_reason.value if t.exit_reason else None,
        "net_pnl": round(t.net_pnl, 2), "pips": pips, "r_multiple": round(t.r_multiple, 2),
        "exploration": is_exploration(t),
    }


def profit_alerts(store: MemoryStore, limit: int = 50, since: datetime | None = None) -> list[dict]:
    """Newest profitable closes across the virtual and real memories."""
    out = []
    for domain in ALERT_DOMAINS:
        for t in store.recent_closed_trades(domain, limit=limit, min_net_pnl=0.0, since=since):
            out.append((t.exit_time, profit_alert(domain, t)))
    out.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in out[:limit]]


def format_profit_alert(a: dict) -> str:
    """One-line text used by notifications. Always says virtual or real."""
    n = a["digits"]
    pips = f" ({a['pips']:+.1f} pips)" if a["pips"] is not None else ""
    tag = "VIRTUAL" if a["simulated"] else "REAL"
    expl = " · exploration" if a["exploration"] else ""
    return (f"{tag} {a['style_label']} {a['side']} {a['symbol']} closed in profit: {a['net_pnl']:+.2f}{pips}, "
            f"{a['entry_price']:.{n}f} → {a['exit_price']:.{n}f}{expl}")
