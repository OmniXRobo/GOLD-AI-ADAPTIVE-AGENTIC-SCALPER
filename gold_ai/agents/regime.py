"""Regime agent with uncertainty: a Gaussian hidden Markov model plus Bayesian online change-point detection.

The rule classifier in `market/features.py` gives one label with no notion of how sure it is. This agent gives a
probability for each regime, a change-point probability, and an `uncertain` flag so a planner can say
"NO TRADE: regime uncertain" instead of acting on a coin-flip label.

Everything is causal: the HMM is fitted on a training window only, and live readings use the forward
(filtering) recursion, which never looks at a later bar. Pure Python (no numpy on the VPS); a few states and
three observation dimensions keep it cheap: one update per closed bar is ~100 multiplications.

Observations per closed bar (computed from that bar and the bars before it):
  ret   log return of the close, in basis points
  lrng  log of the bar's high-low range in basis points (a volatility proxy)
  eff   Kaufman efficiency of the last `eff_window` closes (1 = straight line, 0 = chop)
They are standardised with the training mean and deviation.

State labels come from the fitted state means, not from names chosen in advance: the state with the highest
range is "volatile", the lowest "quiet"; of the rest, a state with high efficiency is trending up or down by the
sign of its mean return, otherwise "ranging". Labels are a description of the fitted model; whether they carry
information about the next hour is measured out of sample by `research/regime_eval.py`.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from ..domain import Candle

OBS_NAMES = ("ret", "lrng", "eff")
_VAR_FLOOR = 1e-3
_LOG_2PI = math.log(2 * math.pi)


def observations(bars: list[Candle], eff_window: int = 12) -> list[tuple[float, float, float] | None]:
    """One observation per bar (None for the first bars, which have no history)."""
    out: list[tuple[float, float, float] | None] = []
    closes = [b.close for b in bars]
    for i, b in enumerate(bars):
        if i < eff_window or closes[i - 1] <= 0 or b.close <= 0:
            out.append(None)
            continue
        ret = math.log(b.close / closes[i - 1]) * 1e4
        rng_bp = max((b.high - b.low) / b.close * 1e4, 0.05)
        w = closes[i - eff_window:i + 1]
        path = sum(abs(y - x) for x, y in zip(w, w[1:]))
        eff = abs(w[-1] - w[0]) / path if path > 0 else 0.0
        out.append((ret, math.log(rng_bp), eff))
    return out


def _logsumexp(xs: list[float]) -> float:
    m = max(xs)
    if m == -math.inf:
        return m
    return m + math.log(sum(math.exp(x - m) for x in xs))


@dataclass
class GaussianHMM:
    """Diagonal-covariance Gaussian HMM fitted with Baum-Welch (scaled forward-backward)."""

    n_states: int = 4
    means: list[list[float]] = field(default_factory=list)
    vars: list[list[float]] = field(default_factory=list)
    trans: list[list[float]] = field(default_factory=list)
    start: list[float] = field(default_factory=list)
    log_likelihood: float | None = None
    iterations: int = 0

    # -- emissions ---------------------------------------------------------------------------------
    def _log_emit(self, x: tuple[float, ...]) -> list[float]:
        out = []
        for mu, var in zip(self.means, self.vars):
            s = 0.0
            for xi, m, v in zip(x, mu, var):
                s += -0.5 * (_LOG_2PI + math.log(v) + (xi - m) ** 2 / v)
            out.append(s)
        return out

    def _emit(self, x: tuple[float, ...]) -> list[float]:
        le = self._log_emit(x)
        m = max(le)
        return [math.exp(v - m) for v in le]   # scaled; the scale cancels in normalised recursions

    # -- fitting -----------------------------------------------------------------------------------
    def _init(self, xs: list[tuple[float, ...]]) -> None:
        """Deterministic start: split the data into volatility quantiles (dimension 1 = log range)."""
        k, d = self.n_states, len(xs[0])
        order = sorted(range(len(xs)), key=lambda i: xs[i][1])
        chunks = [order[j * len(xs) // k:(j + 1) * len(xs) // k] for j in range(k)]
        self.means, self.vars = [], []
        for ch in chunks:
            pts = [xs[i] for i in ch] or xs
            mu = [sum(p[j] for p in pts) / len(pts) for j in range(d)]
            var = [max(sum((p[j] - mu[j]) ** 2 for p in pts) / len(pts), _VAR_FLOOR) for j in range(d)]
            self.means.append(mu)
            self.vars.append(var)
        stay = 0.9
        self.trans = [[stay if i == j else (1 - stay) / (k - 1) for j in range(k)] for i in range(k)]
        self.start = [1.0 / k] * k

    def fit(self, xs: list[tuple[float, ...]], max_iter: int = 30, tol: float = 1e-3) -> "GaussianHMM":
        if len(xs) < self.n_states * 20:
            raise ValueError(f"need at least {self.n_states * 20} observations to fit {self.n_states} states")
        self._init(xs)
        k, n, d = self.n_states, len(xs), len(xs[0])
        prev = None
        for it in range(max_iter):
            emits = [self._emit(x) for x in xs]
            # forward
            alpha: list[list[float]] = []
            scales: list[float] = []
            a = [self.start[j] * emits[0][j] for j in range(k)]
            c = sum(a) or 1e-300
            alpha.append([v / c for v in a])
            scales.append(c)
            for t in range(1, n):
                pa = alpha[-1]
                e = emits[t]
                a = [e[j] * sum(pa[i] * self.trans[i][j] for i in range(k)) for j in range(k)]
                c = sum(a) or 1e-300
                alpha.append([v / c for v in a])
                scales.append(c)
            ll = sum(math.log(s) for s in scales) + sum(max(self._log_emit(x)) for x in xs)
            # backward
            beta = [[1.0] * k for _ in range(n)]
            for t in range(n - 2, -1, -1):
                e, nb = emits[t + 1], beta[t + 1]
                b = [sum(self.trans[i][j] * e[j] * nb[j] for j in range(k)) for i in range(k)]
                c = scales[t + 1]
                beta[t] = [v / c for v in b]
            # posteriors and expected transitions
            gamma = []
            xi_sum = [[0.0] * k for _ in range(k)]
            for t in range(n):
                g = [alpha[t][j] * beta[t][j] for j in range(k)]
                s = sum(g) or 1e-300
                gamma.append([v / s for v in g])
                if t < n - 1:
                    e, nb = emits[t + 1], beta[t + 1]
                    c = scales[t + 1]
                    for i in range(k):
                        ai = alpha[t][i]
                        row = self.trans[i]
                        for j in range(k):
                            xi_sum[i][j] += ai * row[j] * e[j] * nb[j] / c
            # M step
            self.start = [max(v, 1e-6) for v in gamma[0]]
            tot = sum(self.start)
            self.start = [v / tot for v in self.start]
            for i in range(k):
                rs = sum(xi_sum[i]) or 1e-300
                self.trans[i] = [max(v / rs, 1e-6) for v in xi_sum[i]]
                tot = sum(self.trans[i])
                self.trans[i] = [v / tot for v in self.trans[i]]
            for j in range(k):
                w = sum(g[j] for g in gamma) or 1e-300
                mu = [sum(g[j] * x[q] for g, x in zip(gamma, xs)) / w for q in range(d)]
                var = [max(sum(g[j] * (x[q] - mu[q]) ** 2 for g, x in zip(gamma, xs)) / w, _VAR_FLOOR)
                       for q in range(d)]
                self.means[j], self.vars[j] = mu, var
            self.log_likelihood, self.iterations = ll, it + 1
            if prev is not None and abs(ll - prev) < tol * max(1.0, abs(prev)):
                break
            prev = ll
        return self

    # -- causal inference --------------------------------------------------------------------------
    def filter_step(self, prior: list[float] | None, x: tuple[float, ...]) -> list[float]:
        """P(state_t | x_1..x_t) from P(state_{t-1} | x_1..x_{t-1}); `prior=None` uses the start distribution."""
        k = self.n_states
        pred = self.start if prior is None else [sum(prior[i] * self.trans[i][j] for i in range(k)) for j in range(k)]
        e = self._emit(x)
        a = [pred[j] * e[j] for j in range(k)]
        s = sum(a)
        return [v / s for v in a] if s > 0 else [1.0 / k] * k

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GaussianHMM":
        return cls(**d)


class ChangePointDetector:
    """Bayesian online change-point detection (Adams & MacKay 2007) on one series, Normal-Gamma model with
    unknown mean and variance, constant hazard. Run lengths are truncated at `max_run` for constant cost.
    `cp_prob` is the posterior probability that the current run started within the last `recent` bars."""

    def __init__(self, hazard: float = 1 / 250, max_run: int = 300, recent: int = 3,
                 mu0: float = 0.0, kappa0: float = 1.0, alpha0: float = 1.0, beta0: float = 1.0):
        self.h, self.max_run, self.recent = hazard, max_run, recent
        self.prior = (mu0, kappa0, alpha0, beta0)
        self.reset()

    def reset(self) -> None:
        self.run_probs = [1.0]
        self.params = [self.prior]

    @staticmethod
    def _student_logpdf(x: float, mu: float, kappa: float, alpha: float, beta: float) -> float:
        nu = 2 * alpha
        scale2 = beta * (kappa + 1) / (alpha * kappa)
        z = (x - mu) ** 2 / (nu * scale2)
        return (math.lgamma((nu + 1) / 2) - math.lgamma(nu / 2) - 0.5 * math.log(nu * math.pi * scale2)
                - (nu + 1) / 2 * math.log1p(z))

    def update(self, x: float) -> float:
        preds = [math.exp(self._student_logpdf(x, *p)) for p in self.params]
        growth = [rp * pr * (1 - self.h) for rp, pr in zip(self.run_probs, preds)]
        cp = sum(rp * pr * self.h for rp, pr in zip(self.run_probs, preds))
        probs = [cp] + growth
        s = sum(probs)
        probs = [v / s for v in probs] if s > 0 else [1.0] + [0.0] * len(growth)
        new_params = [self.prior]
        for mu, kappa, alpha, beta in self.params:
            new_params.append(((kappa * mu + x) / (kappa + 1), kappa + 1, alpha + 0.5,
                               beta + kappa * (x - mu) ** 2 / (2 * (kappa + 1))))
        if len(probs) > self.max_run:
            tail = sum(probs[self.max_run:])
            probs = probs[:self.max_run]
            probs[-1] += tail
            new_params = new_params[:self.max_run]
        self.run_probs, self.params = probs, new_params
        return self.cp_prob

    @property
    def cp_prob(self) -> float:
        return sum(self.run_probs[:self.recent])


@dataclass
class RegimeReading:
    label: str                       # most probable labelled state, or "uncertain"
    state_label: str                 # most probable labelled state even when uncertain
    confidence: float                # max state posterior
    probabilities: dict[str, float]  # per label (states with the same label are summed)
    change_point_prob: float
    uncertain: bool
    reason: str


@dataclass
class RegimeConfig:
    n_states: int = 4
    eff_window: int = 12
    trend_eff: float = 0.35          # a state is "trending" when its mean efficiency exceeds this
    min_confidence: float = 0.6      # below this max posterior the reading is uncertain
    max_cp_prob: float = 0.5         # above this change-point probability the reading is uncertain
    hazard: float = 1 / 250
    max_iter: int = 30


class RegimeAgent:
    """Fit on a training window of closed bars, then call `update(bar)` on each new closed bar."""

    def __init__(self, cfg: RegimeConfig | None = None):
        self.cfg = cfg or RegimeConfig()
        self.hmm: GaussianHMM | None = None
        self.labels: list[str] = []
        self.norm: tuple[list[float], list[float]] | None = None
        self.cpd = ChangePointDetector(hazard=self.cfg.hazard)
        self._post: list[float] | None = None
        self._window: list[Candle] = []

    @property
    def fitted(self) -> bool:
        return self.hmm is not None

    def _standardise(self, x: tuple[float, float, float]) -> tuple[float, ...]:
        mu, sd = self.norm  # type: ignore[misc]
        return tuple((v - m) / s for v, m, s in zip(x, mu, sd))

    def fit(self, bars: list[Candle]) -> "RegimeAgent":
        raw = [o for o in observations(bars, self.cfg.eff_window) if o is not None]
        if not raw:
            raise ValueError("not enough bars to fit the regime model")
        d = len(raw[0])
        mu = [sum(o[j] for o in raw) / len(raw) for j in range(d)]
        sd = [math.sqrt(sum((o[j] - mu[j]) ** 2 for o in raw) / len(raw)) or 1.0 for j in range(d)]
        self.norm = (mu, sd)
        xs = [self._standardise(o) for o in raw]
        self.hmm = GaussianHMM(self.cfg.n_states).fit(xs, max_iter=self.cfg.max_iter)
        self.labels = self._label_states()
        self.reset_filter()
        return self

    def _label_states(self) -> list[str]:
        assert self.hmm is not None and self.norm is not None
        mu, sd = self.norm
        # state means back in raw units
        raw = [[m * s + c for m, s, c in zip(state, sd, mu)] for state in self.hmm.means]
        k = len(raw)
        order = sorted(range(k), key=lambda j: raw[j][1])
        labels = ["ranging"] * k
        labels[order[-1]] = "volatile"
        if k >= 3:
            labels[order[0]] = "quiet"
        for j in range(k):
            if labels[j] == "ranging" and raw[j][2] >= self.cfg.trend_eff:
                labels[j] = "trending_up" if raw[j][0] > 0 else "trending_down"
        return labels

    def reset_filter(self) -> None:
        self._post = None
        self._window = []
        self.cpd.reset()

    def update(self, bar: Candle) -> RegimeReading:
        """Feed one closed bar (oldest first, no gaps in the order). Causal: uses this bar and earlier ones only."""
        if not self.fitted:
            return RegimeReading("unknown", "unknown", 0.0, {}, 0.0, True, "regime model not fitted")
        self._window.append(bar)
        keep = self.cfg.eff_window + 1
        if len(self._window) > keep:
            self._window = self._window[-keep:]
        obs = observations(self._window, self.cfg.eff_window)[-1]
        if obs is None:
            return RegimeReading("unknown", "unknown", 0.0, {}, 0.0, True, "warming up")
        x = self._standardise(obs)
        self._post = self.hmm.filter_step(self._post, x)   # type: ignore[union-attr]
        cp = self.cpd.update(x[1])                            # change in volatility level
        return self._reading(self._post, cp)

    def _reading(self, post: list[float], cp: float) -> RegimeReading:
        probs: dict[str, float] = {}
        for lab, p in zip(self.labels, post):
            probs[lab] = probs.get(lab, 0.0) + p
        best = max(probs, key=probs.get)
        conf = probs[best]
        reasons = []
        if conf < self.cfg.min_confidence:
            reasons.append(f"regime probability {conf:.2f} < {self.cfg.min_confidence:.2f}")
        if cp > self.cfg.max_cp_prob:
            reasons.append(f"change-point probability {cp:.2f} > {self.cfg.max_cp_prob:.2f}")
        unc = bool(reasons)
        return RegimeReading("uncertain" if unc else best, best, round(conf, 4),
                             {k: round(v, 4) for k, v in sorted(probs.items())}, round(cp, 4), unc,
                             "; ".join(reasons) or f"{best} with probability {conf:.2f}")

    def wait_reason(self, reading: RegimeReading) -> str | None:
        """'NO TRADE: ...' text when the reading is too uncertain to act on, else None."""
        return f"NO TRADE: regime uncertain ({reading.reason})" if reading.uncertain else None

    def to_dict(self) -> dict:
        return {"cfg": asdict(self.cfg), "hmm": self.hmm.to_dict() if self.hmm else None,
                "labels": self.labels, "norm": self.norm}

    @classmethod
    def from_dict(cls, d: dict) -> "RegimeAgent":
        a = cls(RegimeConfig(**d["cfg"]))
        if d.get("hmm"):
            a.hmm = GaussianHMM.from_dict(d["hmm"])
            a.labels = list(d["labels"])
            a.norm = (list(d["norm"][0]), list(d["norm"][1]))
        return a
