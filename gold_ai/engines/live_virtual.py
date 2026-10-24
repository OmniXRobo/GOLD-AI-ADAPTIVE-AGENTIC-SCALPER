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
from dataclasses import asdict, replace
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
        params = params or StrategyParams()
        self.style = params.style
        # Scalping keeps the original key, so its learning from before trade styles existed carries on.
        self.key = f"virtual:{spec.broker}:{spec.symbol}" + ("" if self.style == "scalp" else f":{self.style}")
        params = self._restore_params(params)
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
        self._seed_pending = False
        self._seed_before: datetime | None = None
        # Called with (proposal, tick) for risk-approved, non-exploratory proposals (signal-only mode).
        self.signal_hook = None

    # -- persistence -------------------------------------------------------------
    def _restore_params(self, default: StrategyParams) -> StrategyParams:
        """The owner-promoted strategy for this engine, if one was applied; else `default`."""
        d = self.store.kv_get(f"{self.key}:params")
        if d:
            try:
                p = StrategyParams(**d)
                if p.style == self.style:
                    # Exploration is an engine setting, not part of a promoted strategy.
                    return replace(p, exploration_rate=default.exploration_rate)
            except (TypeError, ValueError) as e:
                log.warning("could not restore promoted strategy for %s (%s); using default", self.key, e)
        return default

    def apply_params(self, params: StrategyParams, version: str | None = None) -> None:
        """Switch to an owner-promoted strategy. The learned model is kept (learning continues), and open
        virtual positions keep the stops they were opened with."""
        if params.style != self.style:
            raise ValueError(f"strategy is for {params.style} trades, this engine trades {self.style}")
        params = replace(params, exploration_rate=self.agent.params.exploration_rate)
        self.agent.params = params
        self.loop.sim.max_hold_seconds = params.max_hold_seconds
        d = asdict(params)
        d["timeframes"] = list(params.timeframes)
        self.store.kv_set(f"{self.key}:params", d)
        self.store.kv_set(f"{self.key}:params_version", version)
        log.info("%s: now trading strategy %s (%s)", self.key, params.version(), version or "unnamed")

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
    def warm_up(self, lookback: timedelta | None = None, now: datetime | None = None,
                chunk: timedelta = timedelta(hours=6)) -> int:
        """Rebuild market state (multi-timeframe bars, features) from ticks already stored for this broker/symbol.

        Market state only: no decisions, fills or learning happen on these ticks, so a restart does
        not have to wait for 20 live M5 bars, and H1/H4 analysis has history. Loaded in `chunk`
        slices to bound memory (~0.5 M ticks per trading day). Returns the number of ticks replayed.

        When the quote source can supply the broker's own bars (`rates`), bars older than the first
        replayed tick are seeded from it first, so a symbol collected for only a few hours still has
        H1/H4/D1 history. Swing replays 2 days of ticks (its bars come from the broker), scalping 7.
        """
        now = now or datetime.now(timezone.utc)
        if lookback is None:
            lookback = timedelta(days=7) if self.style == "scalp" else timedelta(days=2)
        n, first, last = 0, None, None
        t = now - lookback
        while t < now:
            stop = min(t + chunk, now)
            ticks = self.store.load_ticks(self.spec.broker, self.spec.symbol, t, stop)
            if ticks and first is None:
                self._seed_before = ticks[0].time
                self._seed_bars(ticks[0].time)
            for x in ticks:
                self.loop.market.on_tick(x)
                first, last = first or x, x
                n += 1
            t = stop
        if first is None:
            self._seed_before = now
            self._seed_bars(now)
        if last is not None:
            self._last_tick_time = last.time
            log.info("virtual engine warmed up from %d stored ticks (%s .. %s), ready=%s", n,
                     first.time.isoformat(), last.time.isoformat(), self.loop.market.ready)
        return n

    def _seed_bars(self, before: datetime) -> int:
        rates = getattr(self.source, "rates", None)
        if rates is None:
            return 0
        if not getattr(self.source, "server_offset_known", True):
            # Bars need the broker's UTC offset, measured from a moving quote. At a weekend start only
            # some markets move (BTC), so retry from poll_once once the shared connector knows it.
            self._seed_pending = True
            return 0
        self._seed_pending = False
        mtf, added = self.loop.market.mtf, 0
        for tf in mtf.bars:
            try:
                added += mtf.seed(tf, rates(self.spec.symbol, tf, mtf.max_bars), before)
            except Exception as e:   # bars are a convenience; ticks alone still work
                log.warning("%s: could not load broker %s bars (%s)", self.key, tf, e)
        if added:
            log.info("%s: seeded %d broker bars older than %s", self.key, added, before.isoformat())
        return added

    def poll_once(self) -> Tick | None:
        if self._seed_pending and getattr(self.source, "server_offset_known", True):
            self._seed_bars(self._seed_before)
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
            "broker": self.spec.broker, "symbol": self.spec.symbol, "style": self.style,
            "timeframes": list(self.agent.params.timeframes), "strategy_version": self.agent.params.version(),
            "ready": self.loop.market.ready, "equity": self.loop.equity,
            "open_positions": len(self.loop.sim.positions), "ticks_processed": self.loop.stats.ticks,
            "decisions": self.loop.stats.decisions, "model_version": self.agent.model.version(),
            "learning_started": self.store.kv_get(f"{self.key}:learning_started"),
            "last_tick": self._last_tick_time.isoformat() if self._last_tick_time else None,
            "fills": "estimated (virtual)",
        }
