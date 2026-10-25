"""Indicator evaluation: which features carry measurable, out-of-sample information about trade outcomes,
and which are redundant with each other.

Method (docs/AGENTIC_REDESIGN.md §4.3):
- Bars are built from bid ticks; every `stride` M1 bars a feature vector is computed from closed bars only.
- The outcome is a fixed bracket entered at the next bar's open (ask for longs, bid for shorts): stop
  `stop_atr` × M5 ATR, target `rr` × stop, up to `horizon` M1 bars, net of modelled slippage, in R. If stop and
  target fall in the same bar the stop is assumed first (conservative). This is a bar-level approximation used
  only to rank features; strategies themselves are scored tick by tick by the setup harness.
- Information = Spearman rank correlation with the long outcome (short outcomes are reported too), on train
  and validation separately. A feature is "informative" only if it is significant (|ρ|·√(n−1) ≥ 2) with the
  same sign on both. Overlapping outcomes inflate significance, which is why bars are sampled with a stride.
- Redundancy: pairs with |ρ| ≥ `redundant_rho` on train; the less informative feature of a pair is dropped.
The test split is never used here, so feature choice cannot leak into the setups' test scores.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

from ..domain import Candle, SymbolSpec, Tick
from ..market.candles import build_candles, resample
from ..market.features import atr, efficiency_ratio
from ..market.indicators import (adx, bollinger_stats, ema, ema_slope, last_swings, macd, rsi, session_start_utc,
                                 tick_volume_profile, tick_vwap)
from .stats import mean, spearman
from .stream import TickStream

FEATURES = ("ema20_m5_dist", "ema50_m15_slope", "adx_m15", "di_diff_m15", "rsi_m5", "macd_hist_m5",
            "bb_pctb_m5", "bb_bw_pctile_m5", "vwap_dist", "poc_dist", "swing_high_dist", "swing_low_dist",
            "mom_m5_3", "efficiency_m5", "spread_atr", "tick_rate_z")


@dataclass
class FeatureEvalConfig:
    stride: int = 5
    stop_atr: float = 1.0
    rr: float = 1.5
    horizon: int = 60
    slippage_points: int = 10            # entry + exit, adverse
    train_frac: float = 0.5
    validation_frac: float = 0.25
    redundant_rho: float = 0.8
    min_z: float = 2.0


@dataclass
class FeatureResult:
    name: str
    rho_train_long: float | None
    rho_val_long: float | None
    rho_train_short: float | None
    rho_val_short: float | None
    n_train: int
    n_val: int
    informative: bool
    redundant_with: list[str] = field(default_factory=list)
    kept: bool = False


def _closed_upto(bars: list[Candle], secs: int, t_close: datetime, start: int) -> int:
    """Advance index so bars[:i] are bars that closed at or before t_close."""
    i = start
    while i < len(bars) and bars[i].time + timedelta(seconds=secs) <= t_close:
        i += 1
    return i


def feature_vector(m1: list[Candle], m5: list[Candle], m15: list[Candle]) -> dict[str, float] | None:
    if len(m1) < 240 or len(m5) < 60 or len(m15) < 60:
        return None
    a5 = atr(m5)
    if a5 <= 0:
        return None
    c1, c5, c15 = m1[-1].close, [b.close for b in m5[-200:]], [b.close for b in m15[-200:]]
    f: dict[str, float] = {}
    e20 = ema(c5, 20)
    f["ema20_m5_dist"] = (c1 - e20) / a5 if e20 else 0.0
    sl = ema_slope(c15, 50, 5)
    f["ema50_m15_slope"] = sl / a5 if sl is not None else 0.0
    d = adx(m15[-80:])
    f["adx_m15"] = d["adx"] if d else 0.0
    f["di_diff_m15"] = (d["plus_di"] - d["minus_di"]) if d else 0.0
    f["rsi_m5"] = rsi(c5[-60:]) or 50.0
    m = macd(c5)
    f["macd_hist_m5"] = m["histogram"] / a5 if m else 0.0
    bb = bollinger_stats(c5)
    f["bb_pctb_m5"] = bb["pct_b"] if bb else 0.5
    f["bb_bw_pctile_m5"] = bb["bandwidth_pctile"] if bb and bb["bandwidth_pctile"] is not None else 0.5
    vw = tick_vwap(m1[-1440:], session_start_utc(m1[-1].time))
    f["vwap_dist"] = (c1 - vw) / a5 if vw else 0.0
    vp = tick_volume_profile(m1[-240:])
    f["poc_dist"] = (c1 - vp["poc"]) / a5 if vp else 0.0
    hi, lo = last_swings(m5[-60:], 3, 3)
    f["swing_high_dist"] = (hi.price - c1) / a5 if hi else 0.0
    f["swing_low_dist"] = (c1 - lo.price) / a5 if lo else 0.0
    f["mom_m5_3"] = (m5[-1].close - m5[-4].close) / a5
    f["efficiency_m5"] = efficiency_ratio(m5)
    f["spread_atr"] = m1[-1].spread_avg / a5
    vols = [b.tick_volume for b in m1[-60:]]
    mu = mean(vols)
    sd = math.sqrt(sum((v - mu) ** 2 for v in vols) / (len(vols) - 1)) if len(vols) > 1 else 0.0
    f["tick_rate_z"] = (vols[-1] - mu) / sd if sd > 0 else 0.0
    return f


def bracket_outcome(future: list[Candle], side: str, stop_d: float, rr: float, slip: float) -> float:
    """Outcome in R of a bracket entered at future[0].open. Bars are bid-based; ask = bid + bar spread."""
    if not future or stop_d <= 0:
        return 0.0
    sp = future[0].spread_avg
    cost_r = slip / stop_d
    if side == "BUY":
        entry = future[0].open + sp
        for b in future:
            if b.low <= entry - stop_d:
                return -1.0 - cost_r
            if b.high >= entry + rr * stop_d:
                return rr - cost_r
        return (future[-1].close - entry) / stop_d - cost_r
    entry = future[0].open
    for b in future:
        if b.high + b.spread_avg >= entry + stop_d:
            return -1.0 - cost_r
        if b.low + b.spread_avg <= entry - rr * stop_d:
            return rr - cost_r
    return (entry - (future[-1].close + future[-1].spread_avg)) / stop_d - cost_r


def build_dataset(ticks: Iterable[Tick], spec: SymbolSpec, cfg: FeatureEvalConfig) -> list[dict]:
    m1 = build_candles(ticks, "M1")
    m5 = resample(m1, "M5")
    m15 = resample(m1, "M15")
    slip = cfg.slippage_points * spec.point
    rows = []
    j5 = j15 = 0
    for i in range(240, len(m1) - cfg.horizon - 1, cfg.stride):
        t_close = m1[i].time + timedelta(seconds=60)
        j5 = _closed_upto(m5, 300, t_close, j5)
        j15 = _closed_upto(m15, 900, t_close, j15)
        w5 = m5[max(0, j5 - 200):j5]
        f = feature_vector(m1[max(0, i - 1439):i + 1], w5, m15[max(0, j15 - 200):j15])
        if f is None:
            continue
        stop_d = cfg.stop_atr * atr(w5)
        fut = m1[i + 1:i + 1 + cfg.horizon]
        rows.append({"time": t_close, "features": f,
                     "long_r": bracket_outcome(fut, "BUY", stop_d, cfg.rr, slip),
                     "short_r": bracket_outcome(fut, "SELL", stop_d, cfg.rr, slip)})
    return rows


def _sig(rho: float | None, n: int, z: float) -> bool:
    return rho is not None and n > 3 and abs(rho) * math.sqrt(n - 1) >= z


def evaluate_features(ticks: "list[Tick] | TickStream", spec: SymbolSpec, cfg: FeatureEvalConfig | None = None) -> dict:
    cfg = cfg or FeatureEvalConfig()
    stream = ticks if isinstance(ticks, TickStream) else TickStream.from_list(ticks)
    rows = build_dataset(stream, spec, cfg)
    if not rows:
        return {"rows": 0, "features": [], "kept": [], "note": "not enough bars for any feature row"}
    a, z = stream.start, stream.end
    v_start = a + (z - a) * cfg.train_frac
    t_start = v_start + (z - a) * cfg.validation_frac
    train = [r for r in rows if r["time"] < v_start]
    val = [r for r in rows if v_start <= r["time"] < t_start]
    results: dict[str, FeatureResult] = {}
    for name in FEATURES:
        def rho(rs, key):
            return spearman([r["features"][name] for r in rs], [r[key] for r in rs]) if len(rs) >= 3 else None
        rtl, rvl = rho(train, "long_r"), rho(val, "long_r")
        rts, rvs = rho(train, "short_r"), rho(val, "short_r")
        inf_long = _sig(rtl, len(train), cfg.min_z) and _sig(rvl, len(val), cfg.min_z) and rtl * rvl > 0
        inf_short = _sig(rts, len(train), cfg.min_z) and _sig(rvs, len(val), cfg.min_z) and rts * rvs > 0
        results[name] = FeatureResult(name, rtl, rvl, rts, rvs, len(train), len(val), inf_long or inf_short)
    # redundancy on train
    strength = {n: max(abs(results[n].rho_train_long or 0), abs(results[n].rho_train_short or 0)) for n in FEATURES}
    pairs = []
    for i, x in enumerate(FEATURES):
        for y in FEATURES[i + 1:]:
            r = spearman([t["features"][x] for t in train], [t["features"][y] for t in train]) if len(train) >= 3 else None
            if r is not None and abs(r) >= cfg.redundant_rho:
                results[x].redundant_with.append(y)
                results[y].redundant_with.append(x)
                pairs.append((x, y, r))
    dropped = set()
    for x, y, _ in sorted(pairs, key=lambda p: -abs(p[2])):
        if x in dropped or y in dropped:
            continue
        dropped.add(x if strength[x] < strength[y] else y)
    for name, res in results.items():
        res.kept = res.informative and name not in dropped
    return {"rows": len(rows), "train_rows": len(train), "validation_rows": len(val),
            "label": f"bracket {cfg.stop_atr}xATR(M5) stop, {cfg.rr}R target, {cfg.horizon} M1 bars, after slippage; "
                     "bar-level approximation for ranking features only",
            "features": [asdict(r) for r in results.values()],
            "redundant_pairs": [{"a": x, "b": y, "rho": r} for x, y, r in pairs],
            "kept": [n for n, r in results.items() if r.kept],
            "mean_long_r_train": mean([r["long_r"] for r in train]),
            "mean_short_r_train": mean([r["short_r"] for r in train])}


def features_markdown(rep: dict) -> str:
    lines = ["## Feature evaluation", "", f"Rows: {rep['rows']} (train {rep.get('train_rows', 0)}, "
             f"validation {rep.get('validation_rows', 0)}). {rep.get('label', '')}", "",
             "| Feature | ρ long train | ρ long val | ρ short train | ρ short val | Informative | Redundant with | Kept |",
             "|---|---|---|---|---|---|---|---|"]
    f = lambda x: f"{x:+.3f}" if x is not None else "n/a"  # noqa: E731
    for r in rep["features"]:
        lines.append(f"| {r['name']} | {f(r['rho_train_long'])} | {f(r['rho_val_long'])} | {f(r['rho_train_short'])} | "
                     f"{f(r['rho_val_short'])} | {'yes' if r['informative'] else 'no'} | "
                     f"{', '.join(r['redundant_with']) or '—'} | {'yes' if r['kept'] else 'no'} |")
    lines += ["", f"Kept features: {', '.join(rep['kept']) or 'none — no feature showed stable out-of-sample information'}"]
    return "\n".join(lines) + "\n"
