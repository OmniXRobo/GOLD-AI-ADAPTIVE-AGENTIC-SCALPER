"""Authorization-gated MT5 execution adapter (the ONLY module that may call order_send).

Every `execute` call runs these gates in order and stops at the first failure,
without ever calling `order_send`:
  1. emergency stop (persistent flag and risk-engine state)
  2. account real/demo detection (snapshot cross-checked against the live terminal)
  3. authorization: demo path -> auth.demo_execution_allowed; real path -> auth.real_execution_allowed
     (config flag + allowlist + unexpired owner grant + lot cap). Real is disabled by default.
  4. a fresh, independent risk evaluation on the current tick
  5. broker validation: trade mode, volume limits, stop/freeze level, filling mode, order_check
Only then is a TRADE_ACTION_DEAL request built and sent.

Actual fills from REAL accounts are recorded in Memory D (is_estimated_fill=False).
Demo fills are recorded only in the kv log "demo_execution_log" — never in Memory D.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .brokers.mt5_connector import AccountSnapshot
from .domain import ExitReason, MemoryDomain, Side, SimTrade, Tick, TradeProposal, utcnow
from .memory.store import MemoryStore
from .risk.engine import RiskEngine
from .security.auth import AuthService

log = logging.getLogger(__name__)

DEMO_LOG_KEY = "demo_execution_log"
DEFAULT_MAGIC = 20260501

# MetaTrader5 constant fallbacks (values from the official package) for fakes lacking them.
_MT5_DEFAULTS = {
    "TRADE_ACTION_DEAL": 1, "TRADE_ACTION_SLTP": 6, "ORDER_TYPE_BUY": 0, "ORDER_TYPE_SELL": 1,
    "ORDER_FILLING_FOK": 0, "ORDER_FILLING_IOC": 1, "ORDER_FILLING_RETURN": 2, "ORDER_TIME_GTC": 0,
    "TRADE_RETCODE_DONE": 10009, "TRADE_RETCODE_PLACED": 10008, "TRADE_RETCODE_DONE_PARTIAL": 10010,
    "POSITION_TYPE_BUY": 0, "POSITION_TYPE_SELL": 1,
}
_SYMBOL_FILLING_FOK, _SYMBOL_FILLING_IOC = 1, 2
_SYMBOL_TRADE_MODE = {0: "disabled", 1: "longonly", 2: "shortonly", 3: "closeonly", 4: "full"}
_ACCOUNT_TRADE_MODES = {0: "demo", 1: "contest", 2: "real"}
_EXEMODE_MARKET, _EXEMODE_EXCHANGE = 2, 3


@dataclass
class ExecutionResult:
    executed: bool
    stage: str                      # gate that refused, or "sent"
    reasons: list[str]
    account_mode: str = "unknown"   # demo | real | unknown
    request: dict | None = None
    response: dict | None = None
    trade: SimTrade | None = None


@dataclass
class ReconciliationReport:
    matched: list[int] = field(default_factory=list)
    orphans: list[dict] = field(default_factory=list)    # at broker with our magic, not in our records
    missing: list[dict] = field(default_factory=list)    # in our records as open, not at broker
    foreign: list[dict] = field(default_factory=list)    # at broker, other magic (manual/other EA)

    @property
    def clean(self) -> bool:
        return not (self.orphans or self.missing)


def _obj_to_dict(o: Any) -> dict:
    if o is None:
        return {}
    if isinstance(o, dict):
        return dict(o)
    if hasattr(o, "_asdict"):
        return dict(o._asdict())
    return {k: v for k, v in vars(o).items() if not k.startswith("_")}


class MT5ExecutionAdapter:
    def __init__(self, mt5_module: Any, auth: AuthService, risk: RiskEngine, store: MemoryStore, *,
                 mode: str = "demo", magic: int = DEFAULT_MAGIC, deviation_points: int | None = None,
                 symbol: str | None = None, actor: str = "execution"):
        if mode not in ("demo", "real"):
            raise ValueError("mode must be 'demo' or 'real'")
        self.mt5, self.auth, self.risk, self.store = mt5_module, auth, risk, store
        self.mode = mode
        self.magic = magic
        self.deviation = deviation_points if deviation_points is not None else risk.cfg.max_slippage_points
        self.symbol = symbol or risk.spec.symbol
        self.actor = actor

    def c(self, name: str) -> int:
        return getattr(self.mt5, name, _MT5_DEFAULTS[name])

    # -- helpers -------------------------------------------------------------------
    def _refuse(self, stage: str, reasons: list[str], mode: str, **extra) -> ExecutionResult:
        res = ExecutionResult(False, stage, reasons, mode, **extra)
        self.store.audit(self.actor, "execution_refused", {"stage": stage, "reasons": reasons,
                                                           "path": self.mode, "account_mode": mode})
        return res

    def _emergency(self) -> str | None:
        if self.store.kv_get("emergency_stop", False):
            return "emergency stop active"
        if self.risk.state.emergency_stop:
            return f"risk engine emergency stop: {self.risk.state.emergency_reason}"
        return None

    def _detect_account(self, snap: AccountSnapshot) -> tuple[str, list[str]]:
        live = self.mt5.account_info()
        if live is None:
            return "unknown", ["cannot read live account info from terminal"]
        live_mode = _ACCOUNT_TRADE_MODES.get(getattr(live, "trade_mode", -1), "unknown")
        r = []
        if str(getattr(live, "login", "")) != str(snap.login):
            r.append(f"terminal account {getattr(live, 'login', '?')} != snapshot account {snap.login}")
        if live_mode != snap.trade_mode:
            r.append(f"account mode mismatch: terminal={live_mode} snapshot={snap.trade_mode}")
        if live_mode == "unknown":
            r.append("unknown account trade mode")
        if not snap.trade_allowed or not bool(getattr(live, "trade_allowed", False)):
            r.append("trading not allowed on this account")
        return ("real" if live_mode == "real" else "demo" if live_mode in ("demo", "contest") else "unknown"), r

    def _open_positions(self) -> list:
        return list(self.mt5.positions_get(symbol=self.symbol) or [])

    def _filling(self, info) -> int | None:
        flags = int(getattr(info, "filling_mode", 0) or 0)
        if flags & _SYMBOL_FILLING_IOC:
            return self.c("ORDER_FILLING_IOC")
        if flags & _SYMBOL_FILLING_FOK:
            return self.c("ORDER_FILLING_FOK")
        if getattr(info, "trade_exemode", _EXEMODE_MARKET) not in (_EXEMODE_MARKET,):
            return self.c("ORDER_FILLING_RETURN")
        return None

    def _validate_broker(self, side: Side, lots: float, sl: float, tp: float, tick: Tick) -> tuple[list[str], dict]:
        info = self.mt5.symbol_info(self.symbol)
        if info is None:
            return [f"symbol_info({self.symbol}) unavailable"], {}
        r: list[str] = []
        tm = _SYMBOL_TRADE_MODE.get(getattr(info, "trade_mode", 4), "unknown")
        if tm in ("disabled", "closeonly", "unknown") or (tm == "longonly" and side == Side.SELL) or \
                (tm == "shortonly" and side == Side.BUY):
            r.append(f"symbol trade mode {tm} forbids {side.value}")
        vmin, vmax, vstep = info.volume_min, info.volume_max, info.volume_step
        if lots < vmin or lots > vmax:
            r.append(f"volume {lots} outside [{vmin}, {vmax}]")
        elif abs(round(lots / vstep) * vstep - lots) > 1e-9:
            r.append(f"volume {lots} not a multiple of step {vstep}")
        point = info.point
        level = max(int(getattr(info, "trade_stops_level", 0) or 0), int(getattr(info, "trade_freeze_level", 0) or 0))
        min_d = level * point
        price = tick.ask if side == Side.BUY else tick.bid
        if side == Side.BUY:
            if not (sl < price and tp > price):
                r.append("BUY requires sl < price < tp")
        else:
            if not (sl > price and tp < price):
                r.append("SELL requires tp < price < sl")
        if abs(price - sl) < min_d or abs(tp - price) < min_d:
            r.append(f"SL/TP closer than broker stop/freeze level ({level} points)")
        filling = self._filling(info)
        if filling is None:
            r.append("no supported filling mode for market execution")
        return r, {"price": price, "type_filling": filling, "digits": int(getattr(info, "digits", 2))}

    # -- execution ----------------------------------------------------------------
    def execute(self, proposal: TradeProposal, account_snapshot: AccountSnapshot, tick: Tick, *,
                now: datetime | None = None) -> ExecutionResult:
        now = now or utcnow()
        snap = account_snapshot
        if proposal.side not in (Side.BUY, Side.SELL):
            return self._refuse("proposal", ["proposal is not BUY/SELL"], "unknown")

        # 1. emergency stop
        if (why := self._emergency()) is not None:
            return self._refuse("emergency_stop", [why], "unknown")

        # 2. account real/demo detection
        acct_mode, problems = self._detect_account(snap)
        if problems:
            return self._refuse("account", problems, acct_mode)

        # 3. authorization for this path
        if self.mode == "demo":
            ok, why = self.auth.demo_execution_allowed(account_is_real=acct_mode == "real")
        else:
            ok, why = self.auth.real_execution_allowed(snap.login, acct_mode == "real", proposal.lots)
        if not ok:
            return self._refuse("authorization", [why], acct_mode)

        # 4. fresh independent risk evaluation (live open positions, current equity)
        try:
            open_n = len(self._open_positions())
        except Exception as e:
            return self._refuse("risk", [f"cannot read open positions: {e}"], acct_mode)
        self.risk.on_equity(snap.equity, now)
        verdict = self.risk.evaluate(proposal, tick, snap.equity, open_n, now=now)
        if not verdict.approved:
            return self._refuse("risk", verdict.reasons, acct_mode)
        lots = verdict.lots
        if self.mode == "real":  # re-confirm grant against the final size (risk only ever reduces it)
            ok, why = self.auth.real_execution_allowed(snap.login, acct_mode == "real", lots)
            if not ok:
                return self._refuse("authorization", [why], acct_mode)

        # 5. broker validation
        problems, meta = self._validate_broker(proposal.side, lots, proposal.stop_loss, proposal.take_profit, tick)
        if problems:
            return self._refuse("broker_validation", problems, acct_mode)
        d = meta["digits"]
        request = {
            "action": self.c("TRADE_ACTION_DEAL"),
            "symbol": self.symbol,
            "volume": float(lots),
            "type": self.c("ORDER_TYPE_BUY") if proposal.side == Side.BUY else self.c("ORDER_TYPE_SELL"),
            "price": round(meta["price"], d),
            "sl": round(proposal.stop_loss, d),
            "tp": round(proposal.take_profit, d),
            "deviation": int(self.deviation),
            "magic": int(self.magic),
            "comment": f"goldai {proposal.strategy_version}"[:31],
            "type_time": self.c("ORDER_TIME_GTC"),
            "type_filling": meta["type_filling"],
        }
        if hasattr(self.mt5, "order_check"):
            chk = self.mt5.order_check(request)
            if chk is None or getattr(chk, "retcode", 0) not in (0, self.c("TRADE_RETCODE_DONE")):
                return self._refuse("broker_validation",
                                    [f"order_check rejected: {getattr(chk, 'comment', self.mt5.last_error())}"],
                                    acct_mode, request=request)

        # 6. send — the single order_send call site for new positions
        self.store.audit(self.actor, "order_send", {"path": self.mode, "account": snap.login, "request": request})
        res = self.mt5.order_send(request)
        resp = _obj_to_dict(res)
        done = (self.c("TRADE_RETCODE_DONE"), self.c("TRADE_RETCODE_DONE_PARTIAL"), self.c("TRADE_RETCODE_PLACED"))
        if res is None or resp.get("retcode") not in done:
            reason = resp.get("comment") or str(self.mt5.last_error())
            self.store.audit(self.actor, "order_rejected_by_broker", {"response": resp, "reason": reason})
            return ExecutionResult(False, "broker_rejected", [f"broker rejected order: {reason}"], acct_mode,
                                   request, resp)
        trade = self._record_fill(proposal, snap, acct_mode, request, resp, tick)
        return ExecutionResult(True, "sent", [], acct_mode, request, resp, trade)

    def _record_fill(self, p: TradeProposal, snap: AccountSnapshot, acct_mode: str, request: dict, resp: dict,
                     tick: Tick) -> SimTrade:
        ticket = int(resp.get("order") or resp.get("deal") or 0)
        fill = float(resp.get("price") or request["price"])
        lots = float(resp.get("volume") or request["volume"])
        quoted = tick.ask if p.side == Side.BUY else tick.bid
        mpu = self.risk.spec.money_per_price_unit(lots)
        t = SimTrade(
            trade_id=f"mt5-{snap.login}-{ticket}", broker=snap.broker, account=snap.login, symbol=self.symbol,
            side=p.side, lots=lots, entry_time=utcnow(), entry_price=fill, stop_loss=request["sl"],
            take_profit=request["tp"], strategy_version=p.strategy_version, model_version=p.model_version,
            is_estimated_fill=False, slippage_cost=abs(fill - quoted) * mpu,
            initial_risk_money=abs(fill - request["sl"]) * mpu,
            context={"position_ticket": ticket, "deal": resp.get("deal"), "magic": self.magic,
                     "retcode": resp.get("retcode"), "confidence": p.confidence, "account_mode": acct_mode},
            explanation=p.explanation,
        )
        if acct_mode == "real":
            self.store.save_trade(MemoryDomain.REAL, t)
        else:
            self._demo_log_append({"event": "open", "trade_id": t.trade_id, "ticket": ticket, "account": snap.login,
                                   "side": p.side.value, "lots": lots, "price": fill, "sl": t.stop_loss,
                                   "tp": t.take_profit, "time": t.entry_time.isoformat(), "status": "open",
                                   "is_estimated_fill": False, "request": request, "response": resp})
        return t

    def _demo_log_append(self, entry: dict) -> None:
        log_ = list(self.store.kv_get(DEMO_LOG_KEY, []) or [])
        log_.append(entry)
        self.store.kv_set(DEMO_LOG_KEY, log_)

    def demo_log(self) -> list[dict]:
        return list(self.store.kv_get(DEMO_LOG_KEY, []) or [])

    # -- stored open positions ------------------------------------------------------
    def _stored_open(self) -> dict[int, dict]:
        if self.mode == "real":
            return {int(t.context.get("position_ticket", 0)): {"trade_id": t.trade_id, "lots": t.lots,
                                                                "side": t.side.value}
                    for t in self.store.load_trades(MemoryDomain.REAL) if t.exit_time is None
                    and t.symbol == self.symbol}
        state: dict[int, dict] = {}
        for e in self.demo_log():
            if e.get("event") == "open":
                state[int(e["ticket"])] = {"trade_id": e["trade_id"], "lots": e["lots"], "side": e["side"]}
            elif e.get("event") == "close":
                state.pop(int(e["ticket"]), None)
        return state

    def reconcile(self) -> ReconciliationReport:
        """Compare broker positions with our stored open trades (call after every restart)."""
        rep = ReconciliationReport()
        stored = self._stored_open()
        broker_tickets = set()
        for pos in self._open_positions():
            d = _obj_to_dict(pos)
            tk = int(d.get("ticket", 0))
            broker_tickets.add(tk)
            if int(d.get("magic", -1)) != self.magic:
                rep.foreign.append(d)
            elif tk in stored:
                rep.matched.append(tk)
            else:
                rep.orphans.append(d)
        for tk, info in stored.items():
            if tk not in broker_tickets:
                rep.missing.append(dict(info, ticket=tk))
        self.store.audit(self.actor, "reconciliation", {"path": self.mode, "matched": rep.matched,
                                                        "orphans": [o.get("ticket") for o in rep.orphans],
                                                        "missing": [m["ticket"] for m in rep.missing],
                                                        "foreign": len(rep.foreign)})
        return rep

    # -- risk-reducing actions ------------------------------------------------------
    def emergency_close_all(self, actor: str, reason: str = "emergency", *, include_foreign: bool = False) -> list[dict]:
        """Activate the emergency stop, then close every position of this adapter's magic number
        (or every position on the symbol with include_foreign). Allowed even while stopped,
        because it only reduces exposure."""
        self.auth.set_emergency_stop(actor, True, reason)
        self.risk.trigger_emergency_stop(reason)
        results = []
        for pos in self._open_positions():
            d = _obj_to_dict(pos)
            if not include_foreign and int(d.get("magic", -1)) != self.magic:
                continue
            is_buy = int(d.get("type", 0)) == self.c("POSITION_TYPE_BUY")
            tick = self.mt5.symbol_info_tick(self.symbol)
            price = (tick.bid if is_buy else tick.ask) if tick is not None else d.get("price_current", 0.0)
            info = self.mt5.symbol_info(self.symbol)
            filling = self._filling(info) if info is not None else None
            if filling is None:
                filling = self.c("ORDER_FILLING_IOC")
            req = {"action": self.c("TRADE_ACTION_DEAL"), "symbol": self.symbol, "volume": float(d["volume"]),
                   "type": self.c("ORDER_TYPE_SELL") if is_buy else self.c("ORDER_TYPE_BUY"),
                   "position": int(d["ticket"]), "price": price, "deviation": int(self.deviation) * 3,
                   "magic": int(self.magic), "comment": "goldai emergency close",
                   "type_time": self.c("ORDER_TIME_GTC"),
                   "type_filling": filling}
            res = self.mt5.order_send(req)
            resp = _obj_to_dict(res)
            ok = resp.get("retcode") in (self.c("TRADE_RETCODE_DONE"), self.c("TRADE_RETCODE_DONE_PARTIAL"))
            results.append({"ticket": int(d["ticket"]), "closed": ok, "response": resp})
            if ok:
                self._record_close(int(d["ticket"]), float(resp.get("price") or price), ExitReason.EMERGENCY)
        self.store.audit(actor, "emergency_close_all", {"reason": reason, "results": results})
        return results

    def _record_close(self, ticket: int, price: float, reason: ExitReason) -> None:
        if self.mode == "real":
            for t in self.store.load_trades(MemoryDomain.REAL):
                if t.exit_time is None and int(t.context.get("position_ticket", -1)) == ticket:
                    direction = 1.0 if t.side == Side.BUY else -1.0
                    t.exit_time, t.exit_price, t.exit_reason = utcnow(), price, reason
                    t.gross_pnl = (price - t.entry_price) * direction * self.risk.spec.money_per_price_unit(t.lots)
                    t.net_pnl = t.gross_pnl - t.commission + t.swap
                    t.context["pnl_source"] = "fill prices; reconcile commission/swap with deal history"
                    self.store.save_trade(MemoryDomain.REAL, t)
        else:
            self._demo_log_append({"event": "close", "ticket": ticket, "price": price, "reason": reason.value,
                                   "time": utcnow().isoformat(), "is_estimated_fill": False})

    def modify_trailing_stop(self, ticket: int, new_sl: float, tick: Tick | None = None) -> ExecutionResult:
        """TRADE_ACTION_SLTP that may only TIGHTEN the stop. Risk-reducing, so it is allowed under an
        emergency stop, but still validated against the broker stop/freeze level."""
        pos = next((p for p in (self.mt5.positions_get(ticket=ticket) or [])), None)
        if pos is None:
            return self._refuse("trailing", [f"position {ticket} not found"], self.mode)
        d = _obj_to_dict(pos)
        if int(d.get("magic", -1)) != self.magic:
            return self._refuse("trailing", ["position belongs to another magic number"], self.mode)
        is_buy = int(d.get("type", 0)) == self.c("POSITION_TYPE_BUY")
        cur = float(d.get("sl") or 0.0)
        if cur and ((is_buy and new_sl <= cur) or (not is_buy and new_sl >= cur)):
            return self._refuse("trailing", [f"new SL {new_sl} does not tighten current SL {cur}"], self.mode)
        info = self.mt5.symbol_info(self.symbol)
        if tick is None:
            t = self.mt5.symbol_info_tick(self.symbol)
            tick = Tick(utcnow(), t.bid, t.ask) if t is not None else None
        if info is None or tick is None:
            return self._refuse("trailing", ["symbol info / price unavailable"], self.mode)
        level = max(int(getattr(info, "trade_stops_level", 0) or 0), int(getattr(info, "trade_freeze_level", 0) or 0))
        px = tick.bid if is_buy else tick.ask
        if (is_buy and new_sl > px - level * info.point) or (not is_buy and new_sl < px + level * info.point):
            return self._refuse("trailing", [f"new SL violates stop/freeze level ({level} points)"], self.mode)
        digits = int(getattr(info, "digits", 2))
        req = {"action": self.c("TRADE_ACTION_SLTP"), "symbol": self.symbol, "position": int(ticket),
               "sl": round(new_sl, digits), "tp": float(d.get("tp") or 0.0), "magic": int(self.magic)}
        res = self.mt5.order_send(req)
        resp = _obj_to_dict(res)
        ok = resp.get("retcode") == self.c("TRADE_RETCODE_DONE")
        self.store.audit(self.actor, "trailing_stop_modify", {"ticket": ticket, "from": cur, "to": new_sl,
                                                              "ok": ok, "response": resp})
        if not ok:
            return ExecutionResult(False, "broker_rejected", [f"SLTP rejected: {resp.get('comment')}"], self.mode,
                                   req, resp)
        return ExecutionResult(True, "sent", [], self.mode, req, resp)
