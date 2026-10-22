"""The shared tick-driven trading loop used by all three engines.

Per tick: market agent -> (fill pending order) -> manage open positions ->
decision agent -> independent risk veto -> pending order for the NEXT tick.
Orders decided on tick t are filled on tick t+1 at that tick's Bid/Ask, so no
decision can use the price it is filled at (no look-ahead).
Learning updates happen only when a trade closes, i.e. after its outcome is known.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Iterable

from ..agents.decision import TradingDecisionAgent
from ..config import Settings
from ..costs import CostModel
from ..domain import Decision, ExitReason, Side, SimTrade, SymbolSpec, Tick, TradeProposal
from ..market.features import MarketIntelligenceAgent
from ..risk.engine import RiskEngine
from .simulator import PositionSimulator


@dataclass
class LoopStats:
    ticks: int = 0
    decisions: int = 0
    proposals: int = 0
    risk_rejections: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    expired_signals: int = 0


class TradingLoop:
    def __init__(self, settings: Settings, spec: SymbolSpec, agent: TradingDecisionAgent, *,
                 broker: str, account: str, starting_equity: float = 10_000.0, learn: bool = True,
                 simulation: bool = True, decision_every_n_ticks: int = 5,
                 risk: RiskEngine | None = None,
                 on_decision: Callable[[Decision, dict], None] | None = None,
                 on_close: Callable[[SimTrade], None] | None = None):
        self.settings = settings
        self.spec = spec
        self.agent = agent
        self.costs = CostModel(spec, settings.costs)
        self.market = MarketIntelligenceAgent()
        self.risk = risk or RiskEngine.create(settings.risk, spec, starting_equity)
        self.sim = PositionSimulator(self.costs, broker, account, max_open=settings.risk.max_open_positions,
                                     max_hold_seconds=agent.params.max_hold_seconds)
        self.equity = starting_equity
        self.learn = learn
        self.simulation = simulation
        self.every = max(1, decision_every_n_ticks)
        self.pending: tuple[TradeProposal, dict] | None = None
        self.stats = LoopStats()
        self.on_decision = on_decision
        self.on_close = on_close
        self.last_tick: Tick | None = None

    def step(self, tick: Tick) -> list[SimTrade]:
        self.stats.ticks += 1
        self.last_tick = tick
        self.market.on_tick(tick)
        closed = self.sim.on_tick(tick)

        # Fill the order decided on the previous tick (if still valid).
        if self.pending is not None:
            prop, ctx = self.pending
            self.pending = None
            if tick.time <= prop.valid_until:
                self.sim.open(prop, tick, ctx)
            else:
                self.stats.expired_signals += 1

        for t in closed:
            self._after_close(t)

        if self.stats.ticks % self.every == 0 and self.sim.can_open():
            self._decide(tick)
        return closed

    def _decide(self, tick: Tick) -> None:
        state = self.market.state()
        if not state.ready:
            return
        d = self.agent.decide(
            state, self.equity,
            lot_sizer=lambda e, sl: self.risk.position_size(self.equity, e, sl),
            cost_fn=lambda lots: self.costs.estimated_round_trip(lots, tick),
            simulation=self.simulation,
        )
        self.stats.decisions += 1
        verdict_info: dict = {}
        if d.side != Side.WAIT and d.proposal is not None:
            self.stats.proposals += 1
            v = self.risk.evaluate(d.proposal, tick, self.equity, len(self.sim.positions))
            verdict_info = {"approved": v.approved, "reasons": v.reasons, "lots": v.lots}
            if v.approved:
                d.proposal.lots = v.lots
                ctx = {"regime": state.regime, "features": dict(d.features), "confidence": d.confidence,
                       "exploration": "[EXPLORATION]" in d.proposal.explanation}
                self.pending = (d.proposal, ctx)
            else:
                self.stats.risk_rejections += 1
                for r in v.reasons:
                    key = r.split(":")[0].split(" ")[0:2]
                    k = " ".join(key)
                    self.stats.rejection_reasons[k] = self.stats.rejection_reasons.get(k, 0) + 1
        if self.on_decision:
            self.on_decision(d, verdict_info)

    def _after_close(self, t: SimTrade) -> None:
        self.equity += t.net_pnl
        self.risk.on_trade_closed(t.net_pnl)
        self.risk.on_equity(self.equity, t.exit_time)
        if self.learn and "features" in t.context:
            self.agent.learn(t.context["features"], t.side, t.net_pnl > 0)
        if self.on_close:
            self.on_close(t)

    def run(self, ticks: Iterable[Tick]) -> list[SimTrade]:
        out: list[SimTrade] = []
        for tick in ticks:
            if self.risk.state.day is None:
                self.risk.on_equity(self.equity, tick.time)
            out.extend(self.step(tick))
        return out

    def finish(self, reason: ExitReason = ExitReason.END_OF_DATA) -> list[SimTrade]:
        if self.last_tick is None:
            return []
        closed = self.sim.close_all(self.last_tick, reason)
        for t in closed:
            self._after_close(t)
        return closed


def data_hash(ticks: list[Tick]) -> str:
    h = hashlib.sha256()
    for t in ticks:
        h.update(f"{t.time.isoformat()}|{t.bid}|{t.ask}\n".encode())
    return h.hexdigest()[:32]
