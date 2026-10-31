# Setup research — XAUUSD.sd (equiti)

Data: mt5,mt5_history, 62,184,629 ticks, 120,570 M1 bars, 2026-06-28T22:00:20.025000+00:00 → 2026-10-29T11:17:11.951000+00:00
Splits: train 2026-06-28T22:00 → 2026-08-29T04:38; validation 2026-08-29T04:38 → 2026-09-28T19:57; test 2026-09-28T19:57 → 2026-10-29T11:17
Data hash: `1b4cdc9ef050d5302418356dd655d1a0`

_historical research on recorded ticks with modelled costs — NOT live or forward results; a 'candidate' still needs walk-forward and forward virtual evidence_

| Setup | Verdict | Variant | Test trades | Test exp. (R) | 90% CI | PF | Max DD (R) | Random baseline (R) | Val. exp. (R) |
|---|---|---|---|---|---|---|---|---|---|
| trend_pullback | **insufficient_data** | rr=1.5,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 0 | +0.000 | n/a | n/a | 0.0 | -0.111 (19) | +0.000 |
| breakout | **inconclusive** | rr=2,max_hold_seconds=14400,tf_scale=intraday | 39 | +0.007 | -0.306..+0.341 | 1.01 | 8.5 | -0.051 (30) | -0.169 |
| failed_breakout | **insufficient_data** | rr=2,max_hold_seconds=14400,tf_scale=intraday | 0 | +0.000 | n/a | n/a | 0.0 | +0.085 (27) | +0.000 |
| range_reversion | **rejected** | rr=2,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 69 | -0.114 | -0.376..+0.151 | 0.84 | 18.8 | +0.036 (35) | +0.009 |
| liquidity_sweep | **rejected** | rr=1.5,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 64 | +0.012 | -0.240..+0.253 | 1.02 | 11.5 | +0.085 (47) | -0.084 |

## Notes per setup

- **trend_pullback** (trend continuation): fewer than 10 validation trades for every variant; chosen on train; 0 test trades < 30 required. Rejected signals: structural stop too wide: 326, stop on the wrong side of entry: 2, position size below broker minimum: 4.
- **breakout** (breakout): validation expectancy not positive. Rejected signals: structural stop too wide: 27.
- **failed_breakout** (failed breakout): fewer than 10 validation trades for every variant; chosen on train; 0 test trades < 30 required. Rejected signals: structural stop too wide: 16, stop on the wrong side of entry: 1, structural stop too tight: 4, costs too large for the stop: 1.
- **range_reversion** (range mean reversion): test expectancy -0.114R after costs is not positive. Rejected signals: structural stop too wide: 7.
- **liquidity_sweep** (liquidity sweep / market structure): no better than random entry with the same bracket (+0.012R vs +0.085R). Rejected signals: structural stop too tight: 1, structural stop too wide: 3.

## Feature evaluation

Rows: 23922 (train 12183, validation 5510). bracket 1.0xATR(M5) stop, 1.5R target, 60 M1 bars, after slippage; bar-level approximation for ranking features only

| Feature | ρ long train | ρ long val | ρ short train | ρ short val | Informative | Redundant with | Kept |
|---|---|---|---|---|---|---|---|
| ema20_m5_dist | +0.084 | +0.009 | +0.017 | +0.008 | no | rsi_m5, bb_pctb_m5, poc_dist, swing_high_dist, swing_low_dist | no |
| ema50_m15_slope | +0.010 | -0.067 | +0.040 | -0.087 | no | di_diff_m15, vwap_dist | no |
| adx_m15 | +0.063 | +0.123 | +0.054 | +0.137 | yes | — | yes |
| di_diff_m15 | +0.044 | -0.052 | +0.033 | -0.084 | no | ema50_m15_slope | no |
| rsi_m5 | +0.081 | +0.006 | +0.025 | -0.002 | no | ema20_m5_dist, bb_pctb_m5, poc_dist | no |
| macd_hist_m5 | +0.046 | +0.045 | -0.007 | +0.015 | yes | — | yes |
| bb_pctb_m5 | +0.074 | +0.021 | +0.020 | +0.005 | no | ema20_m5_dist, rsi_m5 | no |
| bb_bw_pctile_m5 | +0.322 | +0.297 | +0.274 | +0.249 | yes | — | yes |
| vwap_dist | +0.010 | -0.047 | +0.017 | -0.100 | no | ema50_m15_slope | no |
| poc_dist | +0.074 | -0.009 | +0.025 | +0.010 | no | ema20_m5_dist, rsi_m5 | no |
| swing_high_dist | -0.048 | -0.007 | +0.002 | -0.022 | no | ema20_m5_dist | no |
| swing_low_dist | +0.080 | +0.041 | +0.038 | +0.018 | yes | ema20_m5_dist | no |
| mom_m5_3 | +0.031 | +0.010 | +0.000 | +0.005 | no | — | no |
| efficiency_m5 | +0.055 | +0.034 | +0.032 | +0.026 | yes | — | yes |
| spread_atr | -0.453 | -0.447 | -0.445 | -0.414 | yes | — | yes |
| tick_rate_z | -0.008 | -0.015 | -0.039 | -0.034 | yes | — | yes |

Kept features: adx_m15, macd_hist_m5, bb_bw_pctile_m5, efficiency_m5, spread_atr, tick_rate_z
