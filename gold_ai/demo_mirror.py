"""Demo-account mirror: copies a live virtual engine's entries to the MT5 DEMO account at a fixed lot.

Every entry goes through `MT5ExecutionAdapter.execute` (emergency stop, investigation block, demo/real account
detection, `demo_execution_enabled`, an independent risk evaluation on the real demo equity, broker validation).
The demo path refuses real accounts, so this can never place a real-money order.

- Entry: when the virtual engine fills a non-exploratory proposal (tick t+1), the same SL/TP is sent at
  `demo_execution.lots`. The demo risk engine uses the instrument's risk settings with
  `demo_execution.max_risk_per_trade_pct`; a stop too wide for that risk at the fixed lot is refused.
- Trailing: when the virtual position's stop tightens, the broker stop follows (it can only tighten).
- Exit: broker SL/TP close most trades; when the virtual trade closes for another reason (time limit, trailing,
  emergency) the demo position is closed at market.
- Results come from the broker's deal history and are logged in kv "demo_execution_log" (never in Memory D).
"""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings
from .instruments import settings_for
from .domain import ExitReason, Side, SimTrade, Tick, TradeProposal
from .execution import DEFAULT_MAGIC, MT5ExecutionAdapter, _obj_to_dict
from .memory.store import MemoryStore
from .risk.engine import RiskEngine
from .security.auth import AuthService

log = logging.getLogger(__name__)

STYLE_MAGIC = {"scalp": 0, "swing": 1, "research": 2}


class DemoMirror:
    def __init__(self, engine: Any, conn: Any, auth: AuthService, store: MemoryStore, settings: Settings, *,
                 lots: float, max_risk_per_trade_pct: float, include_exploration: bool = False):
        self.engine, self.conn, self.store = engine, conn, store
        spec = engine.spec
        cfg = settings_for(settings, spec).risk.model_copy(
            update={"risk_per_trade_pct": max_risk_per_trade_pct, "max_lots_per_trade": lots})
        snap = conn.account()
        self.risk = RiskEngine.create(cfg, spec, snap.equity)
        self.lots = lots
        self.include_exploration = include_exploration
        self.magic = DEFAULT_MAGIC + 10 * STYLE_MAGIC.get(engine.style, 9) + 1
        self.adapter = MT5ExecutionAdapter(conn.mt5, auth, self.risk, store, mode="demo", symbol=spec.symbol,
                                           magic=self.magic, actor=f"demo:{engine.key}")
        self.map_key = f"demo_map:{engine.key}"
        self._last_sync = 0.0
        self.last_result: dict | None = None
        engine.loop.on_fill = self.on_fill
        prev_close = engine.loop.on_close

        def _close(t: SimTrade) -> None:
            if prev_close:
                prev_close(t)
            self.on_virtual_close(t)
        engine.loop.on_close = _close
        engine.demo_mirror = self

    # -- state ----------------------------------------------------------------------
    def _map(self) -> dict[str, int]:
        return dict(self.store.kv_get(self.map_key, {}) or {})

    def _save_map(self, m: dict[str, int]) -> None:
        self.store.kv_set(self.map_key, m)

    def _own_positions(self) -> dict[int, dict]:
        out = {}
        for p in self.conn.mt5.positions_get(symbol=self.engine.spec.symbol) or []:
            d = _obj_to_dict(p)
            if int(d.get("magic", -1)) == self.magic:
                out[int(d["ticket"])] = d
        return out

    # -- entry ----------------------------------------------------------------------
    def on_fill(self, prop: TradeProposal, trade: SimTrade, tick: Tick) -> None:
        if "[EXPLORATION]" in prop.explanation and not self.include_exploration:
            return
        if (datetime.now(timezone.utc) - tick.time).total_seconds() > 30:
            return   # warm-up replay of stored ticks: never trade history
        try:
            snap = self.conn.account()
            demo_prop = replace(prop, lots=self.lots)
            res = self.adapter.execute(demo_prop, snap, tick)
        except Exception as e:
            log.exception("demo mirror %s: execute failed", self.engine.key)
            self.last_result = {"time": tick.time.isoformat(), "ok": False, "stage": "error", "reasons": [str(e)]}
            return
        self.last_result = {"time": tick.time.isoformat(), "ok": res.executed, "stage": res.stage, "reasons": res.reasons}
        if res.executed and res.trade is not None:
            self.risk.on_trade_opened(tick.time, demo_prop)
            m = self._map()
            m[trade.trade_id] = int(res.trade.context.get("position_ticket") or 0)
            self._save_map(m)
            log.info("demo mirror %s: opened %s %s lots ticket %s", self.engine.key, prop.side.value, self.lots,
                     m[trade.trade_id])
        else:
            log.info("demo mirror %s: not sent (%s: %s)", self.engine.key, res.stage, "; ".join(res.reasons))

    # -- exits ----------------------------------------------------------------------
    def _close_ticket(self, ticket: int, reason: ExitReason) -> bool:
        pos = self._own_positions().get(ticket)
        if pos is None:
            return False
        mt5 = self.conn.mt5
        c = self.adapter.c
        is_buy = int(pos.get("type", 0)) == c("POSITION_TYPE_BUY")
        t = mt5.symbol_info_tick(self.engine.spec.symbol)
        info = mt5.symbol_info(self.engine.spec.symbol)
        filling = self.adapter._filling(info) if info is not None else None
        req = {"action": c("TRADE_ACTION_DEAL"), "symbol": self.engine.spec.symbol, "volume": float(pos["volume"]),
               "type": c("ORDER_TYPE_SELL") if is_buy else c("ORDER_TYPE_BUY"), "position": ticket,
               "price": (t.bid if is_buy else t.ask) if t is not None else pos.get("price_current", 0.0),
               "deviation": int(self.adapter.deviation) * 3, "magic": self.magic,
               "comment": f"goldai close {reason.value}"[:31], "type_time": c("ORDER_TIME_GTC"),
               "type_filling": filling if filling is not None else c("ORDER_FILLING_IOC")}
        resp = _obj_to_dict(mt5.order_send(req))
        ok = resp.get("retcode") in (c("TRADE_RETCODE_DONE"), c("TRADE_RETCODE_DONE_PARTIAL"))
        self.store.audit(self.adapter.actor, "demo_close", {"ticket": ticket, "reason": reason.value, "ok": ok,
                                                            "response": resp})
        return ok

    def _broker_result(self, ticket: int) -> dict:
        """Net result of a closed position from the broker's deal history (profit + commission + swap)."""
        try:
            deals = self.conn.mt5.history_deals_get(position=ticket) or []
        except Exception:
            deals = []
        ds = [_obj_to_dict(d) for d in deals]
        net = sum(float(d.get("profit", 0)) + float(d.get("commission", 0)) + float(d.get("swap", 0))
                  + float(d.get("fee", 0)) for d in ds)
        out = [d for d in ds if int(d.get("entry", 0)) in (1, 3)]  # DEAL_ENTRY_OUT / OUT_BY
        return {"net": round(net, 2), "deals": len(ds),
                "exit_price": float(out[-1]["price"]) if out else None,
                "exit_comment": out[-1].get("comment") if out else None}

    def _finish(self, trade_id: str, ticket: int, why: str) -> None:
        r = self._broker_result(ticket)
        if r["deals"]:
            self.risk.on_trade_closed(r["net"], datetime.now(timezone.utc))
        self.adapter._demo_log_append({"event": "close", "ticket": ticket, "trade_id": trade_id,
                                       "engine": self.engine.key, "reason": why, "net": r["net"],
                                       "price": r["exit_price"], "broker_comment": r["exit_comment"],
                                       "time": datetime.now(timezone.utc).isoformat(), "is_estimated_fill": False})

    def on_virtual_close(self, t: SimTrade) -> None:
        m = self._map()
        ticket = m.pop(t.trade_id, None)
        if ticket is None:
            return
        try:
            if ticket in self._own_positions():
                self._close_ticket(ticket, t.exit_reason or ExitReason.MANUAL)
            self._finish(t.trade_id, ticket, (t.exit_reason or ExitReason.MANUAL).value)
        except Exception:
            log.exception("demo mirror %s: close of ticket %s failed", self.engine.key, ticket)
            m[t.trade_id] = ticket
        self._save_map(m)

    def sync(self, every_seconds: float = 5.0) -> None:
        """Called from the engine loop: follow the virtual trailing stop and notice broker-side closes."""
        now = time.monotonic()
        if now - self._last_sync < every_seconds:
            return
        self._last_sync = now
        m = self._map()
        if not m:
            return
        own = self._own_positions()
        virtual = {p.trade.trade_id: p for p in self.engine.loop.sim.positions}
        changed = False
        for trade_id, ticket in list(m.items()):
            pos = own.get(ticket)
            if pos is None:            # closed by broker SL/TP (virtual close not seen yet or never)
                self._finish(trade_id, ticket, "broker_sl_tp")
                m.pop(trade_id)
                changed = True
                continue
            vp = virtual.get(trade_id)
            if vp is None or vp.current_sl is None:
                continue
            cur = float(pos.get("sl") or 0.0)
            is_buy = int(pos.get("type", 0)) == 0
            tighter = (vp.current_sl > cur + 1e-9) if is_buy else (cur == 0 or vp.current_sl < cur - 1e-9)
            if tighter:
                self.adapter.modify_trailing_stop(ticket, vp.current_sl)
        if changed:
            self._save_map(m)

    def emergency_close(self) -> None:
        for ticket in list(self._own_positions()):
            self._close_ticket(ticket, ExitReason.EMERGENCY)

    def status(self) -> dict:
        return {"engine": self.engine.key, "lots": self.lots, "magic": self.magic,
                "open_tickets": list(self._map().values()), "last_result": self.last_result,
                "risk_state": {"trades_today": self.risk.state.trades_today,
                               "consecutive_losses": self.risk.state.consecutive_losses,
                               "cooldown_until": self.risk.state.cooldown_until.isoformat()
                               if self.risk.state.cooldown_until else None}}


def summarize_demo_log(entries: list[dict], since: datetime | None = None) -> dict:
    """Totals of closed demo trades from the broker-reported results."""
    closes = [e for e in entries if e.get("event") == "close" and e.get("net") is not None
              and (since is None or datetime.fromisoformat(e["time"]) >= since)]
    wins = [e for e in closes if e["net"] > 0]
    return {"closed": len(closes), "wins": len(wins), "net": round(sum(e["net"] for e in closes), 2),
            "opened": sum(1 for e in entries if e.get("event") == "open"
                          and (since is None or datetime.fromisoformat(e["time"]) >= since))}
