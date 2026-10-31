"""Strategy Selector Agent: picks the agent's strategy from evidence, and refuses when there is none.

For every research lane (a setup + variant traded virtually on live quotes, engines/research_lanes.py) it joins:
- the latest historical research run of the same setup and variant (Memory A, `kind=research`): its verdict and
  test-split result, out of sample, after costs, against a matched random baseline;
- the lane's own forward virtual trades (Memory C, `style=research`): outcomes in R with a bootstrap interval.

A lane is *eligible* only when every owner-set criterion in `PromotionCriteria` holds. Nothing is promoted
automatically: the owner promotes an eligible lane, which makes it the champion for its symbol. A champion's
proposals stop being labelled exploration and may become signals (still virtual fills; real money stays behind
the separate owner grant and is disabled by configuration). A champion is demoted automatically, never promoted,
when its forward results after promotion turn clearly negative, and the owner can demote it at any time.
Every change is audited; no trade or history is altered.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from ..domain import MemoryDomain
from ..research.stats import r_summary
from ..strategies.agent import RuleParams

CHAMPION_KEY = "strategy_champion"
_MATCH_FIELDS = ("setup", "setup_params", "risk_reward", "tf_scale", "trigger_tf", "max_hold_seconds",
                 "min_atr_spread", "min_stop_atr", "max_stop_atr", "max_cost_r", "min_bb_bw_pctile",
                 "hours_utc")


@dataclass
class PromotionCriteria:
    """Owner-configurable (Settings.promotion_criteria). Defaults are deliberately strict."""
    research_verdict: str = "candidate"       # latest research run of this setup/variant must say this
    min_forward_trades: int = 30
    min_forward_expectancy_r: float = 0.05
    forward_ci_above_zero: bool = True        # lower end of the 90% bootstrap interval > 0
    max_forward_drawdown_r: float = 10.0
    # Automatic demotion: after this many trades as champion, demote if the expectancy is below this.
    demote_after_trades: int = 20
    demote_below_expectancy_r: float = -0.15


@dataclass
class LaneEvidence:
    key: str
    symbol: str
    setup: str
    strategy_version: str
    params: dict
    research: dict | None
    forward: dict
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    champion: bool = False


def _fingerprint(params: dict) -> tuple:
    d = asdict(RuleParams(**{k: v for k, v in params.items() if k in RuleParams.__dataclass_fields__}))
    return tuple((k, repr(d.get(k))) for k in _MATCH_FIELDS)


def latest_research(store, symbol: str, params: RuleParams) -> dict | None:
    want = _fingerprint(asdict(params))
    for run in store.list_runs(MemoryDomain.HISTORICAL):        # newest first
        if run["kind"] == "research" and run["symbol"] == symbol and _fingerprint(run["params"]) == want:
            m = run["metrics"] or {}
            return {"run_id": run["run_id"], "created_at": str(run["created_at"]), "verdict": m.get("verdict"),
                    "test": m.get("test"), "validation": m.get("validation"), "baseline_test": m.get("baseline_test"),
                    "period": [str(run["period_start"]), str(run["period_end"])]}
    return None


def forward_trades(store, broker: str, symbol: str, strategy_version: str, since: datetime | None = None):
    ts = [t for t in store.load_trades(MemoryDomain.VIRTUAL, broker=broker, symbols=[symbol])
          if t.strategy_version == strategy_version and t.context.get("style") == "research" and t.exit_time]
    if since is not None:
        ts = [t for t in ts if t.entry_time >= since]
    return ts


def evaluate_lane(store, lane, crit: PromotionCriteria) -> LaneEvidence:
    p: RuleParams = lane.agent.params
    v = p.version()
    research = latest_research(store, lane.spec.symbol, p)
    rs = [t.r_multiple for t in forward_trades(store, lane.spec.broker, lane.spec.symbol, v)
          if t.initial_risk_money > 0]
    fwd = r_summary(rs)
    reasons = []
    if research is None:
        reasons.append("no historical research run for this setup and variant")
    elif research["verdict"] != crit.research_verdict:
        reasons.append(f"research verdict is {research['verdict']!r}, needs {crit.research_verdict!r}")
    if fwd["trades"] < crit.min_forward_trades:
        reasons.append(f"{fwd['trades']} forward trades < {crit.min_forward_trades} required")
    else:
        if fwd["expectancy_r"] < crit.min_forward_expectancy_r:
            reasons.append(f"forward expectancy {fwd['expectancy_r']:+.3f}R < {crit.min_forward_expectancy_r:+.2f}R")
        if crit.forward_ci_above_zero and (fwd["ci90"] is None or fwd["ci90"][0] <= 0):
            reasons.append("forward 90% interval includes zero")
        if fwd["max_drawdown_r"] > crit.max_forward_drawdown_r:
            reasons.append(f"forward drawdown {fwd['max_drawdown_r']:.1f}R > {crit.max_forward_drawdown_r}R")
    champ = (store.kv_get(CHAMPION_KEY, {}) or {}).get(_scope(lane))
    return LaneEvidence(lane.key, lane.spec.symbol, p.setup, v, asdict(p), research, fwd, not reasons, reasons,
                        champion=bool(champ and champ.get("strategy_version") == v))


def _scope(lane) -> str:
    return f"{lane.spec.broker}:{lane.spec.symbol}"


def scoreboard(store, lanes, crit: PromotionCriteria) -> list[dict]:
    return [asdict(evaluate_lane(store, lane, crit)) for lane in lanes]


def promote(store, lane, crit: PromotionCriteria, owner_user) -> dict:
    """Owner-only, and only for an eligible lane. One champion per broker/symbol; the previous one is replaced."""
    if getattr(owner_user, "role", None) != "owner":
        raise PermissionError("only the owner can promote a strategy")
    ev = evaluate_lane(store, lane, crit)
    if not ev.eligible:
        raise ValueError("not eligible: " + "; ".join(ev.reasons))
    champs = dict(store.kv_get(CHAMPION_KEY, {}) or {})
    entry = {"strategy_version": ev.strategy_version, "lane": lane.key, "setup": ev.setup, "params": ev.params,
             "promoted_by": owner_user.username, "promoted_at": _now(), "evidence": {
                 "research": ev.research, "forward": ev.forward}, "previous": champs.get(_scope(lane))}
    champs[_scope(lane)] = entry
    store.kv_set(CHAMPION_KEY, champs)
    store.audit(owner_user.username, "strategy_promoted", {"scope": _scope(lane), **entry})
    return entry


def demote(store, lane, actor: str, reason: str) -> dict | None:
    champs = dict(store.kv_get(CHAMPION_KEY, {}) or {})
    cur = champs.pop(_scope(lane), None)
    if cur is None or cur.get("strategy_version") != lane.agent.params.version():
        return None
    store.kv_set(CHAMPION_KEY, champs)
    store.audit(actor, "strategy_demoted", {"scope": _scope(lane), "strategy_version": cur["strategy_version"],
                                            "reason": reason})
    return cur


def is_champion(store, lane) -> bool:
    cur = (store.kv_get(CHAMPION_KEY, {}) or {}).get(_scope(lane))
    return bool(cur and cur.get("strategy_version") == lane.agent.params.version())


def check_demotion(store, lane, crit: PromotionCriteria) -> dict | None:
    """Demote a champion whose results since promotion are clearly negative. Called after each lane trade."""
    cur = (store.kv_get(CHAMPION_KEY, {}) or {}).get(_scope(lane))
    if not cur or cur.get("strategy_version") != lane.agent.params.version():
        return None
    since = datetime.fromisoformat(cur["promoted_at"])
    rs = [t.r_multiple for t in forward_trades(store, lane.spec.broker, lane.spec.symbol, cur["strategy_version"],
                                               since) if t.initial_risk_money > 0]
    if len(rs) >= crit.demote_after_trades:
        e = sum(rs) / len(rs)
        if e < crit.demote_below_expectancy_r:
            return demote(store, lane, "strategy_selector",
                          f"expectancy {e:+.3f}R over {len(rs)} trades since promotion < {crit.demote_below_expectancy_r}R")
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
