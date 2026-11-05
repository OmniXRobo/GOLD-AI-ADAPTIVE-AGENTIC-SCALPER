"""Out-of-sample benchmark of regime labelling: does a label tell us anything about the next hour?

Compared on the same bars and chronological split (train / validation / test):
- `rule`:   a bar-only version of the live rule classifier (range ratio and efficiency thresholds)
- `hmm`:    the Gaussian HMM regime agent (`agents/regime.py`), fitted on the train split only, then run causally
            over validation and test with the forward filter
- `random`: labels drawn at random with the HMM's train label frequencies (a matched baseline)

Targets, measured from the close of the labelled bar over the next `horizon` bars:
- future volatility: log of the summed absolute log returns (bp). Score = out-of-sample R² when each label
  predicts the mean future volatility it had on the train split. R² ≤ 0 means the label is no better than one
  overall average.
- direction: for trending labels only, how often the next-`horizon` return has the label's sign (z vs 50 %).

Samples are taken every `horizon` bars, so targets do not overlap and the z-scores are not inflated.
Uncertainty is judged by whether the HMM's "certain" readings predict future volatility better than its
"uncertain" ones, on validation and test separately. Nothing here trades or changes the live engines.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable

from ..agents.regime import RegimeAgent, RegimeConfig
from ..domain import Candle
from ..market.features import efficiency_ratio

METHODS = ("rule", "hmm", "random")


@dataclass
class RegimeEvalConfig:
    horizon: int = 12                 # bars ahead (1 h on M5)
    train_frac: float = 0.5
    validation_frac: float = 0.25
    min_test_samples: int = 200
    min_r2_gain: float = 0.01
    seed: int = 0


def rule_label(bars: list[Candle]) -> str:
    """Bar-only analogue of market.features.classify_regime (the live one also uses tick volatility)."""
    if len(bars) < 48:
        return "unknown"
    short = sum(b.high - b.low for b in bars[-6:]) / 6
    long = sum(b.high - b.low for b in bars[-48:]) / 48
    ratio = short / long if long > 0 else 1.0
    if ratio > 2.0:
        return "volatile"
    if ratio < 0.4:
        return "quiet"
    if efficiency_ratio(bars) > 0.35:
        return "trending_up" if bars[-1].close > bars[-20].close else "trending_down"
    return "ranging"


def _future(bars: list[Candle], i: int, h: int) -> tuple[float, float] | None:
    if i + h >= len(bars) or bars[i].close <= 0:
        return None
    path = 0.0
    for a, b in zip(bars[i:i + h], bars[i + 1:i + h + 1]):
        if a.close <= 0 or b.close <= 0:
            return None
        path += abs(math.log(b.close / a.close)) * 1e4
    ret = math.log(bars[i + h].close / bars[i].close) * 1e4
    return math.log(path + 0.1), ret


def _r2(train: list[tuple[str, float]], test: list[tuple[str, float]]) -> float | None:
    if len(train) < 2 or len(test) < 2:
        return None
    overall = sum(v for _, v in train) / len(train)
    by: dict[str, list[float]] = {}
    for lab, v in train:
        by.setdefault(lab, []).append(v)
    means = {k: sum(vs) / len(vs) for k, vs in by.items() if len(vs) >= 5}
    m_test = sum(v for _, v in test) / len(test)
    sst = sum((v - m_test) ** 2 for _, v in test)
    sse = sum((v - means.get(lab, overall)) ** 2 for lab, v in test)
    return 1 - sse / sst if sst > 0 else None


def _direction(rows: list[dict], key: str) -> dict:
    hits = n = 0
    for r in rows:
        lab = r[key]
        if lab not in ("trending_up", "trending_down") or r["fret"] == 0:
            continue
        n += 1
        hits += (r["fret"] > 0) == (lab == "trending_up")
    z = (hits - n / 2) / math.sqrt(n / 4) if n else None
    return {"n": n, "hit_rate": hits / n if n else None, "z": None if z is None else round(z, 2)}


def _abs_err(train: list[tuple[str, float]], test: list[tuple[str, float]]) -> float | None:
    if not train or not test:
        return None
    overall = sum(v for _, v in train) / len(train)
    by: dict[str, list[float]] = {}
    for lab, v in train:
        by.setdefault(lab, []).append(v)
    means = {k: sum(vs) / len(vs) for k, vs in by.items() if len(vs) >= 5}
    return sum(abs(v - means.get(lab, overall)) for lab, v in test) / len(test)


def evaluate_regimes(bars: list[Candle], cfg: RegimeEvalConfig | None = None, regime_cfg: RegimeConfig | None = None,
                     timeframe: str = "M5", progress: Callable[[str], None] | None = None) -> dict:
    cfg = cfg or RegimeEvalConfig()
    n = len(bars)
    n_tr = int(n * cfg.train_frac)
    n_va = int(n * (cfg.train_frac + cfg.validation_frac))
    report: dict = {"timeframe": timeframe, "bars": n, "horizon_bars": cfg.horizon,
                    "period": [bars[0].time.isoformat(), bars[-1].time.isoformat()] if bars else None,
                    "splits": {"train": n_tr, "validation": n_va - n_tr, "test": n - n_va}}
    if n_tr < 500:
        report.update(verdict="insufficient_data", notes=[f"{n_tr} train bars; at least 500 needed to fit"])
        return report
    agent = RegimeAgent(regime_cfg).fit(bars[:n_tr])
    if progress:
        progress(f"HMM fitted: {agent.hmm.iterations} iterations, states {agent.labels}")
    hmm_labels: list[tuple[str, str, bool, float]] = []
    for b in bars:   # causal pass over every bar; parameters come from train only
        r = agent.update(b)
        hmm_labels.append((r.label, r.state_label, r.uncertain, r.change_point_prob))
    freq: dict[str, int] = {}
    for lab, st, _, _ in hmm_labels[:n_tr]:
        freq[st] = freq.get(st, 0) + 1
    rng = random.Random(cfg.seed)
    choices, weights = list(freq), list(freq.values())

    rows = []
    for i in range(48, n - cfg.horizon, cfg.horizon):
        fut = _future(bars, i, cfg.horizon)
        if fut is None or hmm_labels[i][1] == "unknown":
            continue
        split = "train" if i < n_tr else "validation" if i < n_va else "test"
        if i + cfg.horizon >= n_tr and i < n_tr:
            continue   # purge: a train sample whose target reaches into validation
        if i + cfg.horizon >= n_va and split == "validation":
            continue
        rows.append({"split": split, "rule": rule_label(bars[max(0, i - 199):i + 1]),
                     "hmm": hmm_labels[i][1], "uncertain": hmm_labels[i][2], "cp": hmm_labels[i][3],
                     "random": rng.choices(choices, weights)[0], "fvol": fut[0], "fret": fut[1]})
    by_split = {s: [r for r in rows if r["split"] == s] for s in ("train", "validation", "test")}
    methods = {}
    for m in METHODS:
        tr = [(r[m], r["fvol"]) for r in by_split["train"]]
        res = {}
        for s in ("validation", "test"):
            te = [(r[m], r["fvol"]) for r in by_split[s]]
            r2 = _r2(tr, te)
            counts: dict[str, int] = {}
            for lab, _ in te:
                counts[lab] = counts.get(lab, 0) + 1
            res[s] = {"samples": len(te), "vol_r2": None if r2 is None else round(r2, 4),
                      "direction": _direction(by_split[s], m), "label_counts": counts}
        methods[m] = res
    unc = {}
    tr = [(r["hmm"], r["fvol"]) for r in by_split["train"]]
    for s in ("validation", "test"):
        cert = [(r["hmm"], r["fvol"]) for r in by_split[s] if not r["uncertain"]]
        uncr = [(r["hmm"], r["fvol"]) for r in by_split[s] if r["uncertain"]]
        tot = len(cert) + len(uncr)
        ec, eu = _abs_err(tr, cert), _abs_err(tr, uncr)
        unc[s] = {"certain": len(cert), "uncertain": len(uncr),
                  "certain_share": round(len(cert) / tot, 3) if tot else None,
                  "abs_err_certain": None if ec is None else round(ec, 4),
                  "abs_err_uncertain": None if eu is None else round(eu, 4)}
    report.update(model={"states": agent.labels, "iterations": agent.hmm.iterations,
                         "log_likelihood": agent.hmm.log_likelihood},
                  samples={s: len(v) for s, v in by_split.items()}, methods=methods, uncertainty=unc)
    report.update(_verdict(report, cfg))
    return report


def _verdict(rep: dict, cfg: RegimeEvalConfig) -> dict:
    notes = []
    test_n = rep["samples"]["test"]
    if test_n < cfg.min_test_samples:
        return {"verdict": "insufficient_data",
                "notes": [f"{test_n} test samples; {cfg.min_test_samples} needed"]}
    m = rep["methods"]
    hv, ht = m["hmm"]["validation"]["vol_r2"], m["hmm"]["test"]["vol_r2"]
    rv, rt = m["rule"]["validation"]["vol_r2"], m["rule"]["test"]["vol_r2"]
    better = (hv is not None and ht is not None and hv > 0 and ht > 0
              and ht >= max(rt or 0.0, 0.0) + cfg.min_r2_gain and hv >= max(rv or 0.0, 0.0))
    u = rep["uncertainty"]
    helps = all(u[s]["abs_err_certain"] is not None and u[s]["abs_err_uncertain"] is not None
                and u[s]["abs_err_certain"] < u[s]["abs_err_uncertain"] for s in ("validation", "test"))
    for s in ("validation", "test"):
        d = m["hmm"][s]["direction"]
        if d["n"] and d["z"] is not None and abs(d["z"]) < 2:
            notes.append(f"{s}: HMM trending labels do not predict direction (z={d['z']}, n={d['n']})")
    notes.append("uncertainty flag separates better from worse readings on validation and test" if helps
                 else "uncertainty flag did not separate better from worse readings on both splits")
    verdict = "hmm_better_than_rule" if better else "hmm_not_better_than_rule"
    return {"verdict": verdict, "uncertainty_helps": helps, "notes": notes}


def regime_markdown(rep: dict) -> str:
    lines = [f"# Regime benchmark ({rep['timeframe']}, {rep['bars']} bars, horizon {rep['horizon_bars']} bars)", ""]
    if rep.get("period"):
        lines.append(f"Period {rep['period'][0]} → {rep['period'][1]}. Splits (bars): {rep['splits']}.")
    lines.append(f"**Verdict: {rep['verdict']}**" + (f" · uncertainty helps: {rep['uncertainty_helps']}"
                                                    if "uncertainty_helps" in rep else ""))
    lines.append("")
    if "methods" in rep:
        lines.append(f"HMM states: {', '.join(rep['model']['states'])} ({rep['model']['iterations']} EM iterations). "
                     f"Samples: {rep['samples']}.")
        lines += ["", "| Method | Split | Samples | Future-vol R² | Trend calls | Trend hit rate | z |",
                  "|---|---|---|---|---|---|---|"]
        for meth, res in rep["methods"].items():
            for s in ("validation", "test"):
                r = res[s]
                d = r["direction"]
                hr = "-" if d["hit_rate"] is None else f"{d['hit_rate']:.3f}"
                lines.append(f"| {meth} | {s} | {r['samples']} | {r['vol_r2']} | {d['n']} | {hr} | {d['z']} |")
        lines += ["", "| Split | Certain | Uncertain | Certain share | Abs err certain | Abs err uncertain |",
                  "|---|---|---|---|---|---|"]
        for s, u in rep["uncertainty"].items():
            lines.append(f"| {s} | {u['certain']} | {u['uncertain']} | {u['certain_share']} | "
                         f"{u['abs_err_certain']} | {u['abs_err_uncertain']} |")
    lines += ["", "Notes:"] + [f"- {x}" for x in rep.get("notes", [])]
    lines.append("")
    lines.append("Research only: no live engine uses the regime agent until this benchmark passes on real ticks.")
    return "\n".join(lines) + "\n"
