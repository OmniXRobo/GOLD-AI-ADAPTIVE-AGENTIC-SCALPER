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
