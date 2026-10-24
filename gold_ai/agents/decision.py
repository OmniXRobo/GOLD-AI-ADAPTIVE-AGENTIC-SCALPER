"""Trading Decision Agent: adaptive, calibrated BUY / SELL / WAIT decisions.

Design:
- Candidate generators propose a direction from market structure (momentum
  continuation, mean reversion at support/resistance). They are hypotheses only.
- An online logistic model per direction estimates P(TP before SL) from the full
  feature vector, updated from every closed trade's realized outcome.
- A reliability calibrator maps model probability to the empirically observed hit
  rate (Beta-prior shrinkage), so confidence reflects outcomes, not model scores.
- A trade is proposed only if calibrated expectancy after costs is positive and the
  model has enough samples. Otherwise WAIT. Exploration (taking low-evidence trades
  to gather data) is allowed only in simulation engines and is labeled as such.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from ..domain import Decision, Side, TradeProposal
from ..market.features import FEATURE_NAMES, MarketState

_LEARN_FEATURES = tuple(n for n in FEATURE_NAMES if n not in ("atr_m1", "atr_m5"))


@dataclass
class StrategyParams:
    sl_atr_mult: float = 1.5
    risk_reward: float = 1.5
    trailing_start_r: float = 1.0       # activate trailing after +1R
    trailing_distance_r: float = 0.8
    min_confidence: float = 0.55
    min_samples: int = 50               # per direction before non-exploratory trades
    max_hold_seconds: int = 3600
    signal_validity_seconds: int = 60
    exploration_rate: float = 0.0       # 0 for signal/live; >0 only in simulation
    use_momentum: bool = True
    use_mean_reversion: bool = True
    momentum_threshold: float = 0.3
    reversion_distance_atr: float = 0.5
    # Trade style and the (fast, base, slow) bar timeframes the features are computed on. Scalping reads
    # M1/M5/M15; swing reads M15/H1/H4, so its ATR, SL/TP and support/resistance are hourly-scale.
    style: str = "scalp"
    timeframes: tuple[str, str, str] = ("M1", "M5", "M15")

    def __post_init__(self) -> None:
        self.timeframes = tuple(self.timeframes)   # JSON/API params arrive as lists
        if self.style not in STYLES:
            raise ValueError(f"unknown trade style {self.style!r}; expected one of {', '.join(STYLES)}")

    def version(self) -> str:
        d = asdict(self)
        # Fields added after the first versions are left out at their defaults, so scalping strategy
        # versions recorded before trade styles existed keep the same id.
        for k in ("style", "timeframes"):
            if d[k] == _DEFAULTS[k]:
                d.pop(k)
        blob = json.dumps(d, sort_keys=True).encode()
        return "strat-" + hashlib.sha256(blob).hexdigest()[:10]


STYLES = ("scalp", "swing")
STYLE_LABELS = {"scalp": "Scalping", "swing": "Swing"}
_DEFAULTS = {"style": "scalp", "timeframes": ("M1", "M5", "M15")}


def style_params(style: str, **overrides) -> StrategyParams:
    """Starting strategy for a trade style. Swing holds for up to 3 days with stops on the hourly ATR and
    a 2R target; it trades far less often, so it is allowed to signal after 30 closed trades per direction
    instead of 50 (the confidence, expectancy and risk gates are the same)."""
    if style == "scalp":
        base: dict = {}
    elif style == "swing":
        base = dict(style="swing", timeframes=("M15", "H1", "H4"), sl_atr_mult=1.5, risk_reward=2.0,
                    trailing_start_r=1.2, trailing_distance_r=1.0, max_hold_seconds=3 * 86400,
                    signal_validity_seconds=300, min_samples=30)
    else:
        raise ValueError(f"unknown trade style {style!r}")
    return StrategyParams(**{**base, **overrides})


class OnlineLogistic:
    """L2-regularized logistic regression trained by SGD, one sample at a time."""

    def __init__(self, n: int, lr: float = 0.05, l2: float = 1e-3):
        self.w = [0.0] * n
        self.b = 0.0
        self.lr, self.l2 = lr, l2
        self.n_updates = 0

    def predict(self, x: list[float]) -> float:
        z = self.b + sum(wi * xi for wi, xi in zip(self.w, x))
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def update(self, x: list[float], y: float) -> None:
        p = self.predict(x)
        g = p - y
        lr = self.lr / math.sqrt(1 + self.n_updates / 100)
        self.w = [wi - lr * (g * xi + self.l2 * wi) for wi, xi in zip(self.w, x)]
        self.b -= lr * g
        self.n_updates += 1

    def to_dict(self) -> dict:
        return {"w": self.w, "b": self.b, "lr": self.lr, "l2": self.l2, "n": self.n_updates}

    @classmethod
    def from_dict(cls, d: dict) -> "OnlineLogistic":
        m = cls(len(d["w"]), d["lr"], d["l2"])
        m.w, m.b, m.n_updates = list(d["w"]), d["b"], d["n"]
        return m


class Calibrator:
    """Reliability bins: predicted-probability bucket -> observed hit rate with Beta(a,b) prior."""

    def __init__(self, bins: int = 10, prior_a: float = 2.0, prior_b: float = 2.0):
        self.bins = bins
        self.hits = [0] * bins
        self.total = [0] * bins
        self.a, self.b = prior_a, prior_b

    def _idx(self, p: float) -> int:
        return min(self.bins - 1, max(0, int(p * self.bins)))

    def calibrate(self, p: float) -> float:
        i = self._idx(p)
        return (self.hits[i] + self.a) / (self.total[i] + self.a + self.b)

    def update(self, p: float, hit: bool) -> None:
        i = self._idx(p)
        self.total[i] += 1
        self.hits[i] += int(hit)

    def table(self) -> list[dict]:
        return [{"bin": f"{i / self.bins:.1f}-{(i + 1) / self.bins:.1f}", "n": self.total[i],
                 "observed": (self.hits[i] / self.total[i]) if self.total[i] else None}
                for i in range(self.bins)]

    def to_dict(self) -> dict:
        return {"hits": self.hits, "total": self.total, "a": self.a, "b": self.b}

    @classmethod
    def from_dict(cls, d: dict) -> "Calibrator":
        c = cls(len(d["hits"]), d["a"], d["b"])
        c.hits, c.total = list(d["hits"]), list(d["total"])
        return c


def _vec(features: dict[str, float]) -> list[float]:
    # Squash to keep SGD stable on heavy-tailed market features.
    return [math.tanh(features.get(k, 0.0) / 3.0) for k in _LEARN_FEATURES]


@dataclass
class ModelState:
    buy: OnlineLogistic = field(default_factory=lambda: OnlineLogistic(len(_LEARN_FEATURES)))
    sell: OnlineLogistic = field(default_factory=lambda: OnlineLogistic(len(_LEARN_FEATURES)))
    calibrator: Calibrator = field(default_factory=Calibrator)

    def version(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True).encode()
        return "model-" + hashlib.sha256(blob).hexdigest()[:10]

    def to_dict(self) -> dict:
        return {"features": list(_LEARN_FEATURES), "buy": self.buy.to_dict(), "sell": self.sell.to_dict(),
                "calibrator": self.calibrator.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "ModelState":
        if d.get("features") != list(_LEARN_FEATURES):
            raise ValueError("model feature schema mismatch")
        return cls(OnlineLogistic.from_dict(d["buy"]), OnlineLogistic.from_dict(d["sell"]),
                   Calibrator.from_dict(d["calibrator"]))


class TradingDecisionAgent:
    def __init__(self, params: StrategyParams | None = None, model: ModelState | None = None, seed: int = 0):
        self.params = params or StrategyParams()
        self.model = model or ModelState()
        self.rng = random.Random(seed)

    # -- decision ----------------------------------------------------------
    def candidates(self, f: dict[str, float]) -> list[tuple[Side, str]]:
        p = self.params
        out: list[tuple[Side, str]] = []
        if p.use_momentum:
            m = f["mom_m5_3"] + 0.5 * f["mom_m1_5"]
            if m > p.momentum_threshold and f["tick_velocity"] > 0:
                out.append((Side.BUY, f"momentum continuation (m={m:.2f})"))
            elif m < -p.momentum_threshold and f["tick_velocity"] < 0:
                out.append((Side.SELL, f"momentum continuation (m={m:.2f})"))
        if p.use_mean_reversion:
            if f["dist_sup_atr"] < p.reversion_distance_atr and f["wick_bias_m1"] > 0.2:
                out.append((Side.BUY, f"rejection near support ({f['dist_sup_atr']:.2f} ATR)"))
            if f["dist_res_atr"] < p.reversion_distance_atr and f["wick_bias_m1"] < -0.2:
                out.append((Side.SELL, f"rejection near resistance ({f['dist_res_atr']:.2f} ATR)"))
        return out

    def decide(self, state: MarketState, equity: float, lot_sizer, cost_fn, simulation: bool) -> Decision:
        """lot_sizer(entry, sl) -> lots ; cost_fn(lots) -> expected round-trip cost (money)."""
        f = state.features
        if not state.ready or state.last_tick is None:
            return Decision(Side.WAIT, 0.0, "insufficient market history (warming up)", features=f)
        atr5 = f["atr_m5"]
        if atr5 <= 0:
            return Decision(Side.WAIT, 0.0, "zero volatility estimate", features=f)
        cands = self.candidates(f)
        if not cands:
            return Decision(Side.WAIT, 0.0, f"no setup in regime '{state.regime}'", features=f)

        p = self.params
        x = _vec(f)
        best: tuple[float, Side, str, float, bool] | None = None
        for side, why in cands:
            model = self.model.buy if side == Side.BUY else self.model.sell
            raw = model.predict(x)
            conf = self.model.calibrator.calibrate(raw)
            mature = model.n_updates >= p.min_samples
            # expected value in R units: conf*RR - (1-conf)
            ev_r = conf * p.risk_reward - (1 - conf)
            if best is None or ev_r > best[0]:
                best = (ev_r, side, why, conf, mature)
        assert best is not None
        ev_r, side, why, conf, mature = best
        exploring = False
        if not mature or conf < p.min_confidence or ev_r <= 0:
            if simulation and self.rng.random() < p.exploration_rate:
                exploring = True
            else:
                reason = ("model immature" if not mature else
                          f"confidence {conf:.2f} below {p.min_confidence}" if conf < p.min_confidence else
                          f"non-positive expectancy {ev_r:.2f}R")
                return Decision(Side.WAIT, conf, f"{why}; WAIT: {reason}", features=f)

        tick = state.last_tick
        entry = tick.ask if side == Side.BUY else tick.bid
        sl_d = p.sl_atr_mult * atr5 + tick.spread
        sl = entry - sl_d if side == Side.BUY else entry + sl_d
        tp = entry + sl_d * p.risk_reward if side == Side.BUY else entry - sl_d * p.risk_reward
        lots = lot_sizer(entry, sl)
        if lots <= 0:
            return Decision(Side.WAIT, conf, f"{why}; WAIT: position size below broker minimum", features=f)
        cost = cost_fn(lots)
        prop = TradeProposal(
            side=side, entry=entry, stop_loss=sl, take_profit=tp, lots=lots, confidence=conf,
            valid_until=tick.time + timedelta(seconds=p.signal_validity_seconds),
            trailing_start=p.trailing_start_r * sl_d, trailing_distance=p.trailing_distance_r * sl_d,
            expected_cost=cost,
            explanation=f"{side.value}: {why}; regime={state.regime}; calibrated conf={conf:.2f}; "
                        f"EV={ev_r:.2f}R{' [EXPLORATION]' if exploring else ''}",
            strategy_version=p.version(), model_version=self.model.version(), style=p.style,
        )
        return Decision(side, conf, prop.explanation, prop, f)

    # -- learning ------------------------------------------------------------
    def learn(self, features: dict[str, float], side: Side, won: bool) -> None:
        x = _vec(features)
        model = self.model.buy if side == Side.BUY else self.model.sell
        raw = model.predict(x)
        self.model.calibrator.update(raw, won)
        model.update(x, 1.0 if won else 0.0)
