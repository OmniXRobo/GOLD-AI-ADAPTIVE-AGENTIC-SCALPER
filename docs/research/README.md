# Research reports

Reports produced by `python -m gold_ai research` on real stored ticks, committed exactly as generated
(the `.md` and `.json` files are not edited). Interpretation lives here, separate from the reports.

## 2026-10-25 — Equiti demo, XAUUSD.sd, 2026-10-18 22:00 → 2026-10-23 20:57 UTC
Files: `research-XAUUSD.sd-20261025T143255Z.md` / `.json`. 3,285,567 real ticks (collector + broker history),
6,897 M1 bars, about 5 trading days. Splits: train ~2.5 days, validation ~1.2 days, test ~1.2 days.

What it shows
- **No verdict is possible for any setup.** Every setup is `insufficient_data`: 0–11 test trades against the 30
  required. Five trading days is far too little history for a scalping strategy to be judged.
- `legacy_rejection` (the incumbent S/R rejection) was +0.91R per trade on 11 test trades but −0.44R on validation.
  This is not evidence of an edge: the sign flipped between periods, and 11 trades cannot separate skill from luck.
- `trend_pullback`, `failed_breakout`, `range_reversion`, `liquidity_sweep` and `legacy_momentum` were negative on
  the test split. `failed_breakout`'s interval (−1.10..−0.45R) is entirely below zero even on 9 trades.
- `breakout` took no trades: in this week the compression filter (Bollinger bandwidth in its lowest 30%) and a
  fresh M1 close outside the hourly range almost never coincided.
- The most common reason signals were dropped was **"costs too large for the stop"** (round-trip costs above 0.25R).
- Feature evaluation kept only two of 16 indicators: `spread_atr` (spread relative to M5 ATR; strongly negative
  for both directions) and `bb_bw_pctile_m5` (band width; positive for longs). The spread result is partly
  mechanical, because outcomes are measured after costs, but it agrees with the rejection counts: on M1/M5
  stops, Equiti's XAUUSD.sd spread is a large share of the risk. Trend, momentum, RSI/MACD, VWAP and structure
  distances showed no stable out-of-sample information in this week.

What follows from it
1. More history before any conclusion: backfill weeks of broker ticks (research now streams ticks from the
   database in 6-hour chunks, so long periods no longer need to fit in memory).
2. Cost is the first obstacle: the next research round should test trading only when volatility is large
   relative to spread, and stops on M5/M15 structure rather than M1, before any new entry idea.
3. Nothing here changes the live virtual engines, and no setup is promoted.

## Round 2 grid (prepared 2026-10-25, not yet run on real data)
`research` now takes `--variants`, a preset name or a JSON list of rule overrides crossed with the R:R grid; the variant is chosen on
validation like R:R. Round 2 tests the two cost ideas above against the plain setups:

```
python -m gold_ai --config config.local.json research --broker equiti --symbol XAUUSD.sd --rr 1.5,2.0 --variants cost-round2
```

- `min_atr_spread: 10` trades only when M5 ATR is at least 10 spreads (about 2.7 USD on Equiti's ~0.27 spread).
- `trigger_tf: M5` triggers on M5 closes and takes the structural stop from M5 bars (wider stops, costs a smaller
  share of the risk). Bar counts in setup parameters are then M5 bars.
- 7 setups × 2 R:R × 4 variants = 56 lanes plus 7 baselines. Choosing among more variants raises the chance that the
  best one looks good by luck, which is why the test split and the random baseline still decide the verdict.

## Round 3 grid (prepared 2026-10-26, not yet run on real data)
Round 2 (12.6 M ticks, reported by the VPS thread; the report itself is still to be committed here) found no
setup profitable after costs; S/R rejection came out at about 0R. Round 3 keeps the setup logic and moves every
timeframe one step slower (`tf_scale: intraday`): triggers on M5 (or M15) closes, ATR and location on M15, trend
on H1, held up to 4 h (8 h). Stops become several times the ~0.27 spread, so costs are a small share of the risk.
The legacy setups read the scalping features, so they are left out:

```
python -m gold_ai --config config.local.json research --broker equiti --symbol XAUUSD.sd --rr 1.5,2.0 --variants intraday-round3 --setups trend_pullback,breakout,failed_breakout,range_reversion,liquidity_sweep
```

The random baseline for each setup uses the same scale (M5 decisions, M15-ATR stop), so the comparison stays fair.
A setup becomes a candidate only with ≥30 test trades, a positive test expectancy whose interval is above zero,
and a result better than its baseline; then it goes to walk-forward before it may trade in the virtual engine.
