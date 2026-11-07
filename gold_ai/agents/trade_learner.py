"""Trade-History Learner: re-reads every closed virtual trade and measures, honestly, what the agent has learned.

The decision agent learns online, one closed trade at a time. This agent looks back over the whole history of one
engine (broker / symbol / style, Memory C) and answers: had the model only taken the trades it approved at each
moment, what would it have earned? It replays the trades in entry order with no lookahead: before a trade is
scored, the model has learned only from trades that had closed by that trade's entry time (prequential, or
"predict then learn", evaluation). Every score is therefore out of sample.

It then tries a small grid of approval thresholds (minimum calibrated confidence). The threshold is chosen on
the first part of the history and reported on the rest, so the choice itself is out of sample too. When the
chosen threshold clearly beats the engine's current one on the held-out trades, with enough trades and an
interval above zero, it is registered as a `validated` candidate. Like self-healing candidates, it is never
activated automatically: the owner promotes it, and the adaptive family's investigation still blocks promotion
until the owner closes it.

Limits: the history holds only trades the engine actually took (approved plus exploration), not every candidate it
saw; fills are virtual estimates; and nothing here changes trades or learning history.
"""
from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

from ..domain import MemoryDomain, Side, SimTrade
from ..research.stats import r_summary
from .decision import _LEARN_FEATURES, ModelState, StrategyParams, _vec

HISTORY_KEY = "trade_learner_history"
THRESHOLDS = (0.50, 0.55, 0.60, 0.65, 0.70)


@dataclass
class LearnerCriteria:
    min_trades: int = 60                    # closed trades with features before anything is measured
    holdout_frac: float = 0.3               # last share of the history, used only to report the chosen threshold
    min_holdout_selected: int = 20          # approved trades the candidate needs on the held-out part
    min_improvement_r: float = 0.05         # candidate expectancy must beat the current threshold's by this much


@dataclass
class LearnerReport:
    report_id: str
    created_at: str
    broker: str
    symbol: str
    style: str
    trades: int
    period: list[str] | None
    current_threshold: float
    all_trades: dict                         # every replayed trade, as taken
    by_threshold: dict[str, dict]            # threshold -> {"select": r_summary, "holdout": r_summary}
    chosen_threshold: float | None
    holdout_current: dict | None
    holdout_chosen: dict | None
    holdout_all: dict | None                 # every held-out trade, as taken: the filter must beat this
    brier: float | None                      # out-of-sample Brier score of the calibrated probability
    top_features: dict[str, list]            # direction -> [(feature, weight)] largest absolute weights at the end
    context_signals: list[dict] = field(default_factory=list)   # recorded context fields vs outcome (screen only)
    trades_with_context: int = 0
    registered_version: str | None = None
    verdict: str = "insufficient_data"
    reasons: list[str] = field(default_factory=list)
    label: str = ("replay of recorded virtual trades (estimated fills), predict-then-learn with no lookahead; "
                  "not live or real-money results")


def _features(t: SimTrade) -> dict | None:
    f = t.context.get("features")
    return f if isinstance(f, dict) and f else None


def replay(trades: list[SimTrade], params: StrategyParams) -> list[tuple[SimTrade, float, float]]:
    """(trade, calibrated probability of a profit, expectancy in R) for each trade, scored before the model learns
    it and only after learning from trades that had closed by its entry time."""
    model = ModelState()
    order = sorted(trades, key=lambda t: t.entry_time)
    pending = sorted(order, key=lambda t: t.exit_time)
    j, out = 0, []
    for t in order:
        while j < len(pending) and pending[j].exit_time <= t.entry_time:
            done = pending[j]
            x = _vec(_features(done))
            m = model.buy if done.side == Side.BUY else model.sell
            model.calibrator.update(m.predict(x), done.net_pnl > 0)
            m.update(x, 1.0 if done.net_pnl > 0 else 0.0)
            model.payoff(done.side).update(done.r_multiple)
            j += 1
        m = model.buy if t.side == Side.BUY else model.sell
        conf = model.calibrator.calibrate(m.predict(_vec(_features(t))))
        pay = model.payoff(t.side)
        ev = conf * pay.win_r(params.risk_reward) - (1 - conf) * pay.loss_r(1.0)
        mature = m.n_updates >= params.min_samples
        out.append((t, conf if mature else float("nan"), ev))
    return out


def _rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 10:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return sxy / (sx * sy) if sx > 0 and sy > 0 else None


def context_signals(trades: list[SimTrade], holdout_frac: float, min_n: int = 30) -> list[dict]:
    """Rank correlation of each recorded context field (market/trade_context.py) with the trade's outcome in R,
    measured separately on the earlier and the later part of the history. A field counts as informative only when
    both parts agree in sign and are not tiny; this is a screen for what to test next, not a trading rule."""
    ts = sorted((t for t in trades if isinstance(t.context.get("context"), dict)), key=lambda t: t.entry_time)
    cut = int(len(ts) * (1 - holdout_frac))
    names = sorted({k for t in ts for k, v in t.context["context"].items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)})
    out = []
    for name in names:
        parts = []
        for part in (ts[:cut], ts[cut:]):
            pairs = [(t.context["context"][name], t.r_multiple) for t in part
                     if isinstance(t.context["context"].get(name), (int, float))]
            parts.append((spearman([a for a, _ in pairs], [b for _, b in pairs]), len(pairs)))
        (r1, n1), (r2, n2) = parts
        if n1 + n2 < min_n:
            continue
        informative = (r1 is not None and r2 is not None and r1 * r2 > 0 and min(abs(r1), abs(r2)) >= 0.1)
        out.append({"field": name, "rho_earlier": None if r1 is None else round(r1, 3), "n_earlier": n1,
                    "rho_later": None if r2 is None else round(r2, 3), "n_later": n2, "informative": informative})
    return sorted(out, key=lambda d: -min(abs(d["rho_earlier"] or 0), abs(d["rho_later"] or 0)))


def _approved(rows, threshold: float) -> list[float]:
    return [t.r_multiple for t, conf, ev in rows if not math.isnan(conf) and conf >= threshold and ev > 0]


def _top(model: ModelState, k: int = 5) -> dict[str, list]:
    out = {}
    for name, m in (("buy", model.buy), ("sell", model.sell)):
        pairs = sorted(zip(_LEARN_FEATURES, m.w), key=lambda p: -abs(p[1]))[:k]
        out[name] = [[f, round(w, 4)] for f, w in pairs]
    return out


def _final_model(trades: list[SimTrade]) -> ModelState:
    model = ModelState()
    for t in sorted(trades, key=lambda t: t.exit_time):
        x = _vec(_features(t))
        m = model.buy if t.side == Side.BUY else model.sell
        model.calibrator.update(m.predict(x), t.net_pnl > 0)
        m.update(x, 1.0 if t.net_pnl > 0 else 0.0)
        model.payoff(t.side).update(t.r_multiple)
    return model


def evaluate(trades: list[SimTrade], params: StrategyParams, *, broker: str, symbol: str,
             crit: LearnerCriteria | None = None) -> LearnerReport:
    crit = crit or LearnerCriteria()
    ts = [t for t in trades if t.exit_time is not None and t.initial_risk_money > 0 and _features(t)]
    rep = LearnerReport(f"learn-{uuid.uuid4().hex[:12]}", datetime.now(timezone.utc).isoformat(), broker, symbol,
                        params.style, len(ts), None, params.min_confidence, r_summary([t.r_multiple for t in ts]),
                        {}, None, None, None, None, None, {})
    rep.trades_with_context = sum(isinstance(t.context.get("context"), dict) for t in ts)
    rep.context_signals = context_signals(ts, crit.holdout_frac)
    if len(ts) < crit.min_trades:
        rep.reasons.append(f"{len(ts)} closed trades with features < {crit.min_trades} required")
        return rep
    rows = replay(ts, params)
    rep.period = [rows[0][0].entry_time.isoformat(), rows[-1][0].entry_time.isoformat()]
    cut = int(len(rows) * (1 - crit.holdout_frac))
    sel, hold = rows[:cut], rows[cut:]
    scored = [(conf, t.net_pnl > 0) for t, conf, _ in rows if not math.isnan(conf)]
    rep.brier = sum((c - y) ** 2 for c, y in scored) / len(scored) if scored else None
    for th in sorted({*THRESHOLDS, params.min_confidence}):
        rep.by_threshold[f"{th:.2f}"] = {"select": r_summary(_approved(sel, th)),
                                         "holdout": r_summary(_approved(hold, th))}
    eligible = {k: v for k, v in rep.by_threshold.items() if v["select"]["trades"] >= crit.min_holdout_selected}
    rep.top_features = _top(_final_model(ts))
    if not eligible:
        rep.reasons.append("no threshold approved enough trades on the selection part of the history")
        return rep
    best = max(eligible, key=lambda k: eligible[k]["select"]["expectancy_r"])
    rep.chosen_threshold = float(best)
    rep.holdout_chosen = rep.by_threshold[best]["holdout"]
    rep.holdout_current = rep.by_threshold[f"{params.min_confidence:.2f}"]["holdout"]
    hc, cur = rep.holdout_chosen, rep.holdout_current
    if hc["trades"] < crit.min_holdout_selected:
        rep.reasons.append(f"{hc['trades']} held-out approved trades < {crit.min_holdout_selected} required")
    if hc["trades"] and (hc["ci90"] is None or hc["ci90"][0] <= 0):
        rep.reasons.append("held-out 90% interval includes zero")
    if hc["trades"] and hc["expectancy_r"] < (cur["expectancy_r"] if cur["trades"] else 0.0) + crit.min_improvement_r:
        rep.reasons.append("held-out expectancy does not beat the current threshold")
    rep.holdout_all = r_summary([t.r_multiple for t, _, _ in hold])
    if hc["trades"] and hc["expectancy_r"] < rep.holdout_all["expectancy_r"] + crit.min_improvement_r:
        rep.reasons.append("held-out expectancy does not beat taking every trade (the filter adds nothing)")
    if rep.chosen_threshold == params.min_confidence:
        rep.reasons.append("the current threshold is already the best on the selection part")
    rep.verdict = "candidate" if not rep.reasons else "no_change"
    return rep


class TradeHistoryLearner:
    def __init__(self, store, crit: LearnerCriteria | None = None):
        self.store, self.crit = store, crit or LearnerCriteria()

    def run(self, engine, actor: str = "trade_learner") -> LearnerReport:
        style = getattr(engine, "style", "scalp")
        trades = [t for t in self.store.load_trades(MemoryDomain.VIRTUAL, broker=engine.spec.broker,
                                                    symbols=[engine.spec.symbol])
                  if t.context.get("style", "scalp") == style]
        params = engine.agent.params
        rep = evaluate(trades, params, broker=engine.spec.broker, symbol=engine.spec.symbol, crit=self.crit)
        if rep.verdict == "candidate":
            cand = replace(params, min_confidence=rep.chosen_threshold)
            version = f"learn-{cand.version()[6:]}-{uuid.uuid4().hex[:6]}"
            notes = {"broker": engine.spec.broker, "symbol": engine.spec.symbol, "style": style,
                     "source": "trade_history_learner", "report_id": rep.report_id,
                     "holdout_chosen": rep.holdout_chosen, "holdout_current": rep.holdout_current}
            d = asdict(cand)
            d["timeframes"] = list(cand.timeframes)
            self.store.register_model(version, cand.version(), d, engine.agent.model.to_dict(),
                                      parent=engine.agent.model.version(), stage="validated",
                                      notes=json.dumps(notes, default=str))
            rep.registered_version = version
        hist = list(self.store.kv_get(HISTORY_KEY, []) or [])
        hist.append(asdict(rep))
        self.store.kv_set(HISTORY_KEY, hist[-200:])
        self.store.audit(actor, "trade_history_learning", {"report_id": rep.report_id, "engine": engine.key,
                                                           "trades": rep.trades, "verdict": rep.verdict,
                                                           "registered": rep.registered_version})
        return rep

    def latest(self) -> dict[str, dict]:
        """Newest report per engine scope."""
        out: dict[str, dict] = {}
        for r in self.store.kv_get(HISTORY_KEY, []) or []:
            out[f"{r['broker']}:{r['symbol']}:{r['style']}"] = r
        return out
