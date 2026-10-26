# Setup research — XAUUSD.sd (equiti)

Data: mt5,mt5_history, 12,559,446 ticks, 27,883 M1 bars, 2026-09-25T16:02:36.071000+00:00 → 2026-10-23T20:56:59.628000+00:00
Splits: train 2026-09-25T16:02 → 2026-10-09T18:29; validation 2026-10-09T18:29 → 2026-10-16T19:43; test 2026-10-16T19:43 → 2026-10-23T20:56
Data hash: `ef80cace5f21a98ad1b0f0632d198b65`

_historical research on recorded ticks with modelled costs — NOT live or forward results; a 'candidate' still needs walk-forward and forward virtual evidence_

| Setup | Verdict | Variant | Test trades | Test exp. (R) | 90% CI | PF | Max DD (R) | Random baseline (R) | Val. exp. (R) |
|---|---|---|---|---|---|---|---|---|---|
| trend_pullback | **rejected** | rr=1.5 | 48 | -0.054 | -0.315..+0.227 | 0.91 | 9.3 | +0.000 (0) | -0.055 |
| breakout | **insufficient_data** | rr=1.5 | 21 | -0.420 | -0.728..-0.100 | 0.37 | 9.8 | -0.100 (24) | -0.035 |
| failed_breakout | **rejected** | rr=1.5,min_atr_spread=10,trigger_tf=M5 | 32 | -0.432 | -0.715..-0.122 | 0.42 | 13.8 | +0.032 (28) | +0.041 |
| range_reversion | **insufficient_data** | rr=1.5,min_atr_spread=10 | 5 | -1.075 | -1.099..-1.053 | n/a | 5.4 | +0.118 (34) | -0.176 |
| liquidity_sweep | **rejected** | rr=1.5 | 40 | -0.219 | -0.540..+0.105 | 0.70 | 8.8 | +0.036 (36) | -0.134 |
| legacy_momentum | **insufficient_data** | rr=2,min_atr_spread=10 | 22 | -0.220 | -0.555..+0.171 | 0.62 | 5.8 | +0.155 (45) | -0.131 |
| legacy_rejection | **inconclusive** | rr=1.5,trigger_tf=M5 | 31 | +0.001 | -0.334..+0.319 | 1.00 | 3.5 | -0.702 (6) | +0.119 |

## Notes per setup

- **trend_pullback** (trend continuation): test expectancy -0.054R after costs is not positive. Rejected signals: costs too large for the stop: 45, structural stop too tight: 24, structural stop too wide: 7.
- **breakout** (breakout): 21 test trades < 30 required. Rejected signals: structural stop too wide: 2.
- **failed_breakout** (failed breakout): test expectancy -0.432R after costs is not positive. Rejected signals: volatility too low for the spread: 388, structural stop too wide: 8.
- **range_reversion** (range mean reversion): 5 test trades < 30 required. Rejected signals: volatility too low for the spread: 2022, costs too large for the stop: 30, structural stop too tight: 5, structural stop too wide: 3.
- **liquidity_sweep** (liquidity sweep / market structure): test expectancy -0.219R after costs is not positive. Rejected signals: costs too large for the stop: 64, structural stop too tight: 13, structural stop too wide: 1.
- **legacy_momentum** (momentum continuation (incumbent)): 22 test trades < 30 required. Rejected signals: volatility too low for the spread: 1865.
- **legacy_rejection** (S/R rejection (incumbent)): 90% interval -0.334..+0.319R includes zero. Rejected signals: costs too large for the stop: 1.

## Feature evaluation

Rows: 5386 (train 2609, validation 1395). bracket 1.0xATR(M5) stop, 1.5R target, 60 M1 bars, after slippage; bar-level approximation for ranking features only

| Feature | ρ long train | ρ long val | ρ short train | ρ short val | Informative | Redundant with | Kept |
|---|---|---|---|---|---|---|---|
| ema20_m5_dist | -0.005 | +0.047 | -0.083 | +0.060 | no | rsi_m5, bb_pctb_m5, poc_dist, swing_high_dist, swing_low_dist | no |
| ema50_m15_slope | -0.052 | -0.013 | -0.102 | +0.126 | no | di_diff_m15, vwap_dist | no |
| adx_m15 | +0.003 | -0.015 | +0.040 | -0.004 | no | — | no |
| di_diff_m15 | -0.059 | -0.022 | -0.076 | +0.106 | no | ema50_m15_slope | no |
| rsi_m5 | -0.015 | +0.017 | -0.076 | +0.066 | no | ema20_m5_dist, bb_pctb_m5, poc_dist | no |
| macd_hist_m5 | +0.037 | +0.099 | +0.014 | +0.041 | no | — | no |
| bb_pctb_m5 | +0.003 | +0.043 | -0.044 | +0.055 | no | ema20_m5_dist, rsi_m5, swing_high_dist, swing_low_dist | no |
| bb_bw_pctile_m5 | +0.253 | +0.317 | +0.301 | +0.267 | yes | — | yes |
| vwap_dist | -0.007 | +0.020 | -0.114 | +0.161 | no | ema50_m15_slope | no |
| poc_dist | +0.008 | -0.019 | -0.036 | +0.066 | no | ema20_m5_dist, rsi_m5 | no |
| swing_high_dist | -0.013 | -0.059 | +0.051 | -0.050 | no | ema20_m5_dist, bb_pctb_m5 | no |
| swing_low_dist | +0.013 | +0.079 | -0.057 | +0.102 | no | ema20_m5_dist, bb_pctb_m5 | no |
| mom_m5_3 | -0.012 | +0.046 | -0.006 | +0.000 | no | — | no |
| efficiency_m5 | +0.023 | +0.035 | +0.055 | -0.019 | no | — | no |
| spread_atr | -0.436 | -0.526 | -0.481 | -0.369 | yes | — | yes |
| tick_rate_z | -0.020 | -0.101 | -0.023 | -0.053 | no | — | no |

Kept features: bb_bw_pctile_m5, spread_atr
