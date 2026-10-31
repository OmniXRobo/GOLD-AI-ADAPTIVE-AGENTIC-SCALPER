"""Forward research lanes: research setups traded virtually on live broker quotes (Memory C, simulation only).

Historical research decides which setups are worth watching. A lane runs one of them on the same read-only quote
source as the live virtual engines, so it builds forward evidence on prices it was never tuned on. Lanes:
- trade only in simulation (the rule agent refuses to propose outside it), with estimated fills, and every trade
  is labelled `[EXPLORATION] research trade` and `style="research"`, so it never counts as a strategy's results,
  never produces a signal (see the champion exception below) and is kept apart from the scalping and swing engines' accounts;
- do not learn online (rules are measured, not fitted), and have no model;
- keep open positions across restarts like the live virtual engines.
Exception: a lane the owner has promoted to champion (agents/strategy_selector.py, only when every evidence
criterion holds) labels its proposals as the champion strategy instead, and they may become signals.
A lane's results are read with `audit-trades --style research` or `/api/trades/virtual`; promoting a setup to the
agent's strategy is a separate, owner-approved step after research, walk-forward and this forward evidence agree.
Which lanes run, and on which instruments, is set by `Settings.research_lanes` / `research_lane_symbols`.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

from ..agents import strategy_selector as selector
from ..config import Settings
from ..domain import SymbolSpec
from ..instruments import settings_for
from ..memory.store import MemoryStore
from ..risk.engine import RiskEngine, measurement_risk
from ..strategies.agent import RuleAgent, RuleParams
from .live_virtual import LiveVirtualEngine, QuoteSource
from .loop import TradingLoop

STYLE = "research"

def lane_params(cfg: dict) -> RuleParams:
    return RuleParams(**{**cfg, "style": STYLE})


class ResearchLaneEngine(LiveVirtualEngine):
    def __init__(self, settings: Settings, spec: SymbolSpec, source: QuoteSource, store: MemoryStore,
                 params: RuleParams, *, account: str = "research", starting_equity: float = 10_000.0,
                 poll_interval: float = 0.25):
        if hasattr(source, "order_send"):
            raise TypeError("research lanes must be given a read-only quote source")
        self.settings, self.spec, self.source, self.store = settings, spec, source, store
        self.style = STYLE
        self.key = f"research:{spec.broker}:{spec.symbol}:{params.version()}"
        self.agent = RuleAgent(params)
        equity = store.kv_get(f"{self.key}:equity", starting_equity)
        # Measured like the research harness (no account-level loss stops), until promoted to champion.
        self._trading_risk = settings_for(settings, spec).risk
        risk = RiskEngine.create(measurement_risk(self._trading_risk), spec, equity)
        self.loop = TradingLoop(settings, spec, self.agent, broker=spec.broker, account=account,
                                starting_equity=equity, learn=False, simulation=True, risk=risk,
                                on_decision=self._on_decision, on_close=self._on_close)
        self._restore_positions()
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._last_tick_time: datetime | None = None
        self.stale_polls = 0
        self._seed_pending = False
        self._seed_before: datetime | None = None
        # Signals are sent only while the owner has promoted this lane to champion (agents/strategy_selector.py);
        # until then every proposal is labelled exploration and the inherited _on_decision never calls the hook.
        self.signal_hook = None
        self.criteria = selector.PromotionCriteria(**settings.promotion_criteria)
        self.refresh_champion()

    def refresh_champion(self) -> bool:
        """A champion trades under the full account risk rules; a lane under observation is measured."""
        self.agent.champion = selector.is_champion(self.store, self)
        self.loop.risk.cfg = self._trading_risk if self.agent.champion else measurement_risk(self._trading_risk)
        return self.agent.champion

    def _on_close(self, t) -> None:
        super()._on_close(t)
        if self.agent.champion and selector.check_demotion(self.store, self, self.criteria) is not None:
            self.refresh_champion()

    def _persist(self) -> None:
        self.store.kv_set(f"{self.key}:equity", self.loop.equity)
        self.store.kv_set(f"{self.key}:open", [self._pos_to_dict(p) for p in self.loop.sim.positions])

    def apply_params(self, params, version: str | None = None) -> None:
        raise TypeError("research lanes are configured in settings, not promoted")

    def warm_up(self, lookback: timedelta | None = None, now: datetime | None = None,
                chunk: timedelta = timedelta(hours=6)) -> int:
        # Intraday setups read H1 bars (trend over ~50 hours). Older bars are seeded from the broker's own history,
        # so 3 days of stored ticks are enough and keep start-up short with several lanes.
        return super().warm_up(lookback or timedelta(days=3), now, chunk)

    def status(self) -> dict:
        p = self.agent.params
        return {
            "broker": self.spec.broker, "symbol": self.spec.symbol, "style": STYLE, "setup": p.setup,
            "params": {"risk_reward": p.risk_reward, "tf_scale": p.tf_scale, "trigger_tf": p.trigger_tf,
                       "max_hold_seconds": p.max_hold_seconds},
            "strategy_version": p.version(), "ready": self.loop.market.ready, "equity": self.loop.equity,
            "open_positions": len(self.loop.sim.positions), "ticks_processed": self.loop.stats.ticks,
            "signals": self.agent.signals, "rejected": dict(self.agent.rejected),
            "last_tick": self._last_tick_time.isoformat() if self._last_tick_time else None,
            "fills": "estimated (virtual research lane)", "champion": self.agent.champion,
        }
