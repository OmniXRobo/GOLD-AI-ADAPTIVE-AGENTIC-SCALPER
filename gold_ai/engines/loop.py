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
import logging

from ..domain import Decision, ExitReason, Side, SimTrade, SymbolSpec, Tick, TradeProposal
from ..instruments import settings_for
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
                 on_close: Callable[[SimTrade], None] | None = None,
                 market: MarketIntelligenceAgent | None = None):
        settings = settings_for(settings, spec)   # per-instrument spread/slippage/session/news limits
        self.settings = settings
        self.spec = spec
        self.agent = agent
        self.costs = CostModel(spec, settings.costs)
        # A shared market agent (research lanes) is fed by the caller, which then calls `process`.
        self.market = market or MarketIntelligenceAgent(timeframes=agent.params.timeframes)
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
        # Optional (proposal, opened virtual trade, fill tick) callback, e.g. the demo-account mirror.
        self.on_fill: Callable[[TradeProposal, SimTrade, Tick], None] | None = None
        self.last_tick: Tick | None = None
        # Optional (tick, market state) -> dict stored as trade.context["context"] when an order is placed
        # (market/trade_context.py). Recorded for later measurement only; it never changes a decision.
        self.context_provider: Callable | None = None

    def step(self, tick: Tick) -> list[SimTrade]:
        return self.process(tick, self.market.on_tick(tick))

    def process(self, tick: Tick, new_bars: dict, state=None) -> list[SimTrade]:
        """Everything after the market agent has seen `tick`. `state` lets lanes that share one market agent
        reuse a single feature computation."""
        self.stats.ticks += 1
        self.last_tick = tick
        if self.risk.state.day != tick.time.date():
            # Day (and week) limits roll over on the first tick of a new day, not only when a trade closes;
            # otherwise a daily block would persist until some trade closed.
            self.risk.on_equity(self.equity, tick.time)
        closed = self.sim.on_tick(tick)

        # Fill the order decided on the previous tick (if still valid).
        if self.pending is not None:
            prop, ctx = self.pending
            self.pending = None
            if tick.time <= prop.valid_until:
                opened = self.sim.open(prop, tick, ctx)
                if opened is not None:
                    self.risk.on_trade_opened(tick.time, prop)
                    if self.on_fill is not None:
                        try:
                            self.on_fill(prop, opened, tick)
                        except Exception:
                            log.exception("on_fill hook failed")
            else:
                self.stats.expired_signals += 1

        for t in closed:
            self._after_close(t)

        # Rule agents decide once per closed bar of their trigger timeframe; the adaptive agent every n ticks.
        gate = getattr(self.agent, "decide_on_bar_close", None)
        due = gate in new_bars if gate else self.stats.ticks % self.every == 0
        if due and self.sim.can_open():
            self._decide(tick, state)
        return closed

    def _decide(self, tick: Tick, state=None) -> None:
        state = state or self.market.state(advance=True)
        if not state.ready:
            return
        d = self.agent.decide(
            state, self.equity,
            lot_sizer=lambda e, sl: self.risk.position_size(self.equity, e, sl),
            cost_fn=lambda lots: self.costs.estimated_round_trip(lots, tick),
            simulation=self.simulation,
            risk_money=lambda e, sl, lots: abs(e - sl) * self.spec.money_per_price_unit(lots),
        )
        self.stats.decisions += 1
        verdict_info: dict = {}
        if d.side != Side.WAIT and d.proposal is not None:
            self.stats.proposals += 1
            self._widen_for_cost(d.proposal, tick)
            market = {"vol_ratio": state.features.get("vol_ratio"), "spread_z": state.features.get("spread_z")}
            v = self.risk.evaluate(d.proposal, tick, self.equity, len(self.sim.positions), market=market,
                                   est_cost=self.costs.estimated_round_trip(d.proposal.lots, tick)
                                   if d.proposal.lots > 0 else None)
            verdict_info = {"approved": v.approved, "reasons": v.reasons, "lots": v.lots,
                            "style": self.agent.params.style, "risk_rule_version": v.rule_version}
            if v.approved:
                d.proposal.lots = v.lots
                ctx = {"regime": state.regime, "features": dict(d.features), "confidence": d.confidence,
                       "style": self.agent.params.style,
                       "exploration": "[EXPLORATION]" in d.proposal.explanation,
                       "ev_after_cost_r": d.proposal.ev_after_cost_r, **d.proposal.meta}
                if self.context_provider is not None:
                    try:
                        ctx["context"] = self.context_provider(tick, state)
                    except Exception as e:
                        ctx["context"] = {"errors": [type(e).__name__]}
                self.pending = (d.proposal, ctx)
            else:
                self.stats.risk_rejections += 1
                for r in v.reasons:
                    key = r.split(":")[0].split(" ")[0:2]
                    k = " ".join(key)
                    self.stats.rejection_reasons[k] = self.stats.rejection_reasons.get(k, 0) + 1
        if self.on_decision:
            self.on_decision(d, verdict_info)

    def _widen_for_cost(self, p: TradeProposal, tick: Tick) -> None:
        """Owner choice (2026-11-25): when costs would exceed `max_cost_to_risk_pct` of the risk, widen the stop
        (and target, keeping the reward:risk ratio and trailing in proportion) until they fit, and size the lot
        down so the money at risk stays within risk_per_trade_pct. Not widened beyond `cost_widen_max_factor`; such a proposal is
        then refused by the risk engine's cost rule as before."""
        cfg = self.risk.cfg
        if cfg.max_cost_to_risk_pct is None or not cfg.widen_stop_for_cost or p.lots <= 0:
            return
        dist = abs(p.entry - p.stop_loss)
        mpu = self.spec.money_per_price_unit(p.lots)
        if dist <= 0 or mpu <= 0:
            return
        cost = self.costs.estimated_round_trip(p.lots, tick)
        need = cost / (cfg.max_cost_to_risk_pct / 100.0 * 0.95) / mpu     # stop distance with 5% headroom
        if need <= dist:
            return
        f = need / dist
        if f > cfg.cost_widen_max_factor:
            return
        sgn = 1.0 if p.side == Side.BUY else -1.0
        rr = p.risk_reward
        p.stop_loss = p.entry - sgn * need
        p.take_profit = p.entry + sgn * need * rr
        if p.trailing_start is not None:
            p.trailing_start *= f
        if p.trailing_distance is not None:
            p.trailing_distance *= f
        lots = self.spec.round_volume(min(p.lots, self.risk.position_size(self.equity, p.entry, p.stop_loss)))
        if lots > 0:
            p.lots = lots
        p.meta = {**p.meta, "stop_widened_for_cost": round(f, 2)}
        p.explanation += f" [stop widened x{f:.2f} so costs stay under {cfg.max_cost_to_risk_pct:g}% of risk]"

    def _after_close(self, t: SimTrade) -> None:
        self.equity += t.net_pnl
        self.risk.on_trade_closed(t.net_pnl, t.exit_time)
        self.risk.on_equity(self.equity, t.exit_time)
        if self.learn and "features" in t.context:
            self.agent.learn(t.context["features"], t.side, t.net_pnl > 0,
                             r=t.r_multiple if t.initial_risk_money > 0 else None)
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
