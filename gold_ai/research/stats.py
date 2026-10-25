"""Small statistics helpers for research reports (no numpy dependency)."""
from __future__ import annotations

import math
import random


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def bootstrap_ci(xs: list[float], n: int = 2000, alpha: float = 0.10, seed: int = 0) -> tuple[float, float] | None:
    """Percentile bootstrap interval for the mean (90 % by default). None for fewer than 5 values."""
    if len(xs) < 5:
        return None
    rng = random.Random(seed)
    k = len(xs)
    means = sorted(sum(xs[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    lo = means[int(alpha / 2 * n)]
    hi = means[min(n - 1, int((1 - alpha / 2) * n))]
    return lo, hi


def ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3 or n != len(b):
        return None
    ma, mb = mean(a), mean(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    return pearson(ranks(a), ranks(b))


def r_summary(rs: list[float], seed: int = 0) -> dict:
    """Trade outcomes in R (net P/L / money at risk): expectancy with interval, profit factor, drawdown in R,
    worst trade and the 5 % tail."""
    n = len(rs)
    if n == 0:
        return {"trades": 0, "expectancy_r": 0.0, "ci90": None, "profit_factor": None, "win_rate": None,
                "max_drawdown_r": 0.0, "worst_r": None, "tail5_r": None, "total_r": 0.0}
    gp = sum(r for r in rs if r > 0)
    gl = -sum(r for r in rs if r <= 0)
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    srt = sorted(rs)
    tail = srt[:max(1, n // 20)]
    return {"trades": n, "expectancy_r": mean(rs), "ci90": bootstrap_ci(rs, seed=seed),
            "profit_factor": (gp / gl) if gl > 0 else None, "win_rate": sum(r > 0 for r in rs) / n,
            "max_drawdown_r": dd, "worst_r": srt[0], "tail5_r": mean(tail), "total_r": sum(rs)}
