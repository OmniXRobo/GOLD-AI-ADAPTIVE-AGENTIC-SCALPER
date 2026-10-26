"""Rule agent: turns one setup's signals into trade proposals for the research harness.

It plugs into the shared `TradingLoop` like the adaptive decision agent, so research trades use exactly
the same next-tick fills, bid/ask, slippage, commission, swap and risk veto as every other engine. It decides
only when an M1 bar closes. It is simulation-only: until a setup has passed research and walk-forward and the
owner has promoted it, `decide` refuses to propose outside simulation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from ..domain import Decision, Side, TradeProposal
from ..market.features import MarketState, atr
from .setups import Setup, SetupContext, make_setup

NO_TRADE = "NO TRADE"


@dataclass
class RuleParams:
    setup: str
    setup_params: dict = field(default_factory=dict)
    risk_reward: float = 1.5
    min_stop_atr: float = 0.3          # reject structural stops tighter than this many M5 ATRs (noise)
    max_stop_atr: float = 3.0          # reject stops wider than this (risk too far from entry)
    max_cost_r: float = 0.25           # reject when round-trip costs exceed this share of the money at risk
    max_hold_seconds: int = 3600
    signal_validity_seconds: int = 60
    style: str = "scalp"
    timeframes: tuple[str, str, str] = ("M1", "M5", "M15")
    # Bars the setup triggers on and takes its structural stop from; bar counts in setup params are in these bars.
    trigger_tf: str = "M1"
    # Trade only when M5 ATR is at least this many spreads (0 = off): costs are small relative to the move.
    min_atr_spread: float = 0.0

    def __post_init__(self) -> None:
        self.timeframes = tuple(self.timeframes)
        if self.trigger_tf not in ("M1", "M5"):
            raise ValueError(f"trigger_tf must be M1 or M5, got {self.trigger_tf!r}")

    def version(self) -> str:
        d = asdict(self)
        for k, default in (("trigger_tf", "M1"), ("min_atr_spread", 0.0)):   # keep earlier version ids
            if d[k] == default:
                d.pop(k)
        blob = json.dumps(d, sort_keys=True, default=str).encode()
        return f"rule-{self.setup}-" + hashlib.sha256(blob).hexdigest()[:8]


class RuleAgent:

    def __init__(self, params: RuleParams, setup: Setup | None = None, cache: dict | None = None):
        """`cache` may be shared by agents that see the same bars (research lanes), so indicators are
        computed once per closed bar."""
        self.params = params
        self.setup = setup or make_setup(params.setup, **params.setup_params)
        self.cache = cache if cache is not None else {}
        self.signals = 0
        self.rejected: dict[str, int] = {}

    @property
    def decide_on_bar_close(self) -> str:
        return self.params.trigger_tf

    def _reject(self, why: str, f: dict) -> Decision:
        self.rejected[why.split(" (")[0]] = self.rejected.get(why.split(" (")[0], 0) + 1
        return Decision(Side.WAIT, 0.0, f"{NO_TRADE}: {why}", features=f)

    def decide(self, state: MarketState, equity: float, lot_sizer, cost_fn, simulation: bool,
               risk_money=None) -> Decision:
        """risk_money(entry, sl, lots) -> money lost at the stop (used to express costs in R)."""
        f = state.features
        if not simulation:
            return Decision(Side.WAIT, 0.0, f"{NO_TRADE}: research setups are simulation-only until promoted",
                            features=f)
        if not state.ready or state.last_tick is None or not state.bars:
            return Decision(Side.WAIT, 0.0, f"{NO_TRADE}: insufficient market history", features=f)
        tick = state.last_tick
        m1 = state.bars.get("M1")
        bar_key = (m1[-1].time, len(m1)) if m1 else None
        if self.cache.get("_bar") != bar_key:
            self.cache.clear()
            self.cache["_bar"] = bar_key
        p = self.params
        if p.min_atr_spread > 0 and tick.spread > 0:
            ratio = atr(state.bars.get("M5", [])) / tick.spread
            if ratio < p.min_atr_spread:
                return self._reject(f"volatility too low for the spread ({ratio:.1f} < {p.min_atr_spread:g} spreads)", f)
        ctx = SetupContext(tick, state.bars, f, state.regime, self.cache, p.trigger_tf)
        sig = self.setup.evaluate(ctx)
        if sig is None:
            return Decision(Side.WAIT, 0.0, f"{NO_TRADE}: no {self.setup.name} setup", features=f)
        self.signals += 1
        a5 = atr(state.bars.get("M5", []))
        entry = tick.ask if sig.side == Side.BUY else tick.bid
        sl_d = entry - sig.stop if sig.side == Side.BUY else sig.stop - entry
        if a5 <= 0 or sl_d <= 0:
            return self._reject("stop on the wrong side of entry", f)
        sl_atr = sl_d / a5
        if sl_atr < p.min_stop_atr:
            return self._reject(f"structural stop too tight ({sl_atr:.2f} ATR < {p.min_stop_atr})", f)
        if sl_atr > p.max_stop_atr:
            return self._reject(f"structural stop too wide ({sl_atr:.2f} ATR > {p.max_stop_atr})", f)
        lots = lot_sizer(entry, sig.stop)
        if lots <= 0:
            return self._reject("position size below broker minimum", f)
        cost = cost_fn(lots)
        at_risk = risk_money(entry, sig.stop, lots) if risk_money else None
        cost_r = cost / at_risk if at_risk else None
        if cost_r is not None and cost_r > p.max_cost_r:
            return self._reject(f"costs too large for the stop ({cost_r:.2f}R > {p.max_cost_r}R)", f)
        tp = entry + sl_d * p.risk_reward if sig.side == Side.BUY else entry - sl_d * p.risk_reward
        expl = (f"{sig.side.value}: {sig.reason} [{self.setup.name}]; regime={state.regime}; "
                f"stop {sl_atr:.2f} ATR; R:R {p.risk_reward:.2f}; [EXPLORATION] research trade")
        prop = TradeProposal(
            side=sig.side, entry=entry, stop_loss=sig.stop, take_profit=tp, lots=lots, confidence=0.0,
            valid_until=tick.time + timedelta(seconds=p.signal_validity_seconds), expected_cost=cost,
            explanation=expl, strategy_version=p.version(), model_version="none", style=p.style,
            meta={"setup": self.setup.name, "sl_atr": sl_atr, "cost_r": cost_r, "evidence": sig.evidence},
        )
        return Decision(sig.side, 0.0, expl, prop, f)

    def learn(self, features: dict, side: Side, won: bool, r: float | None = None) -> None:
        """Rules do not learn online; their outcomes are measured by the research harness."""
