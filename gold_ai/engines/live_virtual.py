"""ENGINE C — Live virtual forward trading on real-time broker quotes. Memory C only.

Reads quotes from any object with `latest_tick(symbol) -> Tick | None` (the read-only
MT5 connector in production). It never has access to an order-sending API, and all
fills are flagged as estimated. Model state, learning-session start and open virtual
positions are persisted so the engine resumes after a restart.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..agents.decision import ModelState, StrategyParams, TradingDecisionAgent
from ..config import Settings
from ..domain import Decision, ExitReason, MemoryDomain, Side, SimTrade, SymbolSpec, Tick
from ..memory.store import MemoryStore
from .loop import TradingLoop
from .simulator import OpenPosition

log = logging.getLogger(__name__)


class QuoteSource(Protocol):
    def latest_tick(self, symbol: str) -> Tick | None: ...


class LiveVirtualEngine:
    def __init__(self, settings: Settings, spec: SymbolSpec, source: QuoteSource, store: MemoryStore, *,
                 params: StrategyParams | None = None, account: str = "virtual", starting_equity: float = 10_000.0,
                 poll_interval: float = 0.25):
        if hasattr(source, "order_send"):
            raise TypeError("live virtual engine must be given a read-only quote source")
        self.settings, self.spec, self.source, self.store = settings, spec, source, store
        self.key = f"virtual:{spec.broker}:{spec.symbol}"
        params = params or StrategyParams()
        model = self._restore_model()
        self.agent = TradingDecisionAgent(params, model)
        equity = store.kv_get(f"{self.key}:equity", starting_equity)
        self.loop = TradingLoop(settings, spec, self.agent, broker=spec.broker, account=account,
                                starting_equity=equity, learn=True, simulation=True,
                                on_decision=self._on_decision, on_close=self._on_close)
        self._restore_positions()
        if store.kv_get(f"{self.key}:learning_started") is None:
            store.kv_set(f"{self.key}:learning_started", datetime.now(timezone.utc).isoformat())
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._last_tick_time: datetime | None = None
        self.stale_polls = 0
        # Called with (proposal, tick) for risk-approved, non-exploratory proposals (signal-only mode).
        self.signal_hook = None

    # -- persistence -------------------------------------------------------------
    def _restore_model(self) -> ModelState:
        d = self.store.kv_get(f"{self.key}:model")
        if d:
            try:
                return ModelState.from_dict(d)
            except (ValueError, KeyError) as e:
                log.warning("could not restore virtual model (%s); starting fresh", e)
        return ModelState()

    def _persist(self) -> None:
        self.store.kv_set(f"{self.key}:model", self.agent.model.to_dict())
        self.store.kv_set(f"{self.key}:equity", self.loop.equity)
        self.store.kv_set(f"{self.key}:open", [self._pos_to_dict(p) for p in self.loop.sim.positions])

    @staticmethod
    def _pos_to_dict(p: OpenPosition) -> dict:
        t = asdict(p.trade)
        t["side"] = p.trade.side.value
        t["entry_time"] = p.trade.entry_time.isoformat()
        return {"trade": t, "trailing_start": p.trailing_start, "trailing_distance": p.trailing_distance,
                "trailing_active": p.trailing_active, "current_sl": p.current_sl}

    def _restore_positions(self) -> None:
        for d in self.store.kv_get(f"{self.key}:open", []) or []:
            t = dict(d["trade"])
            t["side"] = Side(t["side"])
            t["entry_time"] = datetime.fromisoformat(t["entry_time"])
            t["exit_reason"] = None
            self.loop.sim.positions.append(OpenPosition(
                SimTrade(**t), d["trailing_start"], d["trailing_distance"], None,
                trailing_active=d["trailing_active"], current_sl=d["current_sl"]))

    # -- callbacks ----------------------------------------------------------------
    def _on_decision(self, d: Decision, verdict: dict) -> None:
        if d.side != Side.WAIT:
            self.store.save_decision(MemoryDomain.VIRTUAL, self.spec.broker, d, verdict)
            if (self.signal_hook and verdict.get("approved") and d.proposal is not None
                    and "[EXPLORATION]" not in d.proposal.explanation):
                try:
                    self.signal_hook(d.proposal, self.loop.last_tick)
                except Exception:
                    log.exception("signal hook failed")

    def _on_close(self, t: SimTrade) -> None:
        self.store.save_trade(MemoryDomain.VIRTUAL, t)
        self._persist()

    # -- running --------------------------------------------------------------------
    def warm_up(self, lookback: timedelta = timedelta(hours=3), now: datetime | None = None) -> int:
        """Rebuild market state (bars, features) from ticks already stored for this broker/symbol.

        Market state only: no decisions, fills or learning happen on these ticks, so a restart does
        not have to wait for 20 live M5 bars. Returns the number of ticks replayed.
        """
        now = now or datetime.now(timezone.utc)
        ticks = self.store.load_ticks(self.spec.broker, self.spec.symbol, now - lookback, now)
        for t in ticks:
            self.loop.market.on_tick(t)
        if ticks:
            self._last_tick_time = ticks[-1].time
            log.info("virtual engine warmed up from %d stored ticks (%s .. %s), ready=%s", len(ticks),
                     ticks[0].time.isoformat(), ticks[-1].time.isoformat(), self.loop.market.state().ready)
        return len(ticks)

    def poll_once(self) -> Tick | None:
        tick = self.source.latest_tick(self.spec.symbol)
        if tick is None:
            self.stale_polls += 1
            return None
        if self._last_tick_time is not None and tick.time <= self._last_tick_time:
            self.stale_polls += 1
            return None
        self._last_tick_time = tick.time
        opened_before = len(self.loop.sim.positions)
        self.loop.risk.on_equity(self.loop.equity, tick.time)
        self.loop.step(tick)
        if len(self.loop.sim.positions) != opened_before:
            self._persist()
        return tick

    def run(self, max_seconds: float | None = None) -> None:
        start = time.monotonic()
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # keep observing; self-healing agent reads the log
                log.exception("virtual engine poll failed")
            if max_seconds is not None and time.monotonic() - start >= max_seconds:
                break
            self._stop.wait(self.poll_interval)
        self._persist()

    def stop(self) -> None:
        self._stop.set()

    def emergency_close(self) -> list[SimTrade]:
        if self.loop.last_tick is None:
            return []
        out = self.loop.sim.close_all(self.loop.last_tick, ExitReason.EMERGENCY)
        for t in out:
            self.loop._after_close(t)
        return out

    def status(self) -> dict:
        return {
            "broker": self.spec.broker, "symbol": self.spec.symbol, "equity": self.loop.equity,
            "open_positions": len(self.loop.sim.positions), "ticks_processed": self.loop.stats.ticks,
            "decisions": self.loop.stats.decisions, "model_version": self.agent.model.version(),
            "learning_started": self.store.kv_get(f"{self.key}:learning_started"),
            "last_tick": self._last_tick_time.isoformat() if self._last_tick_time else None,
            "fills": "estimated (virtual)",
        }
