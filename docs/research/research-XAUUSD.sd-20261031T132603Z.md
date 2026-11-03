# Setup research — XAUUSD.sd (equiti)

Data: mt5,mt5_history, 62,184,629 ticks, 120,570 M1 bars, 2026-06-28T22:00:20.025000+00:00 → 2026-10-29T11:17:11.951000+00:00
Splits: train 2026-06-28T22:00 → 2026-08-29T04:38; validation 2026-08-29T04:38 → 2026-09-28T19:57; test 2026-09-28T19:57 → 2026-10-29T11:17
Data hash: `1b4cdc9ef050d5302418356dd655d1a0`

_historical research on recorded ticks with modelled costs — NOT live or forward results; a 'candidate' still needs walk-forward and forward virtual evidence; account loss stops (drawdown, daily/weekly loss, loss cooldowns) are off while measuring, per-trade rules apply_

| Setup | Verdict | Variant | Test trades | Test exp. (R) | 90% CI | PF | Max DD (R) | Random baseline (R) | Val. exp. (R) |
|---|---|---|---|---|---|---|---|---|---|
| trend_pullback | **rejected** | rr=2,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 52 | -0.142 | -0.420..+0.138 | 0.78 | 11.5 | -0.168 (47) | +0.205 |
| breakout | **rejected** | rr=2,max_hold_seconds=14400,tf_scale=intraday | 43 | -0.036 | -0.341..+0.268 | 0.94 | 10.9 | +0.049 (30) | -0.189 |
| failed_breakout | **rejected** | rr=2,max_hold_seconds=14400,min_bb_bw_pctile=0.6,tf_scale=intraday | 116 | -0.190 | -0.386..+0.010 | 0.73 | 27.2 | -0.195 (79) | +0.196 |
| range_reversion | **rejected** | rr=2,max_hold_seconds=14400,min_bb_bw_pctile=0.6,tf_scale=intraday | 45 | -0.085 | -0.418..+0.255 | 0.88 | 14.5 | +0.084 (25) | +0.068 |
| liquidity_sweep | **insufficient_data** | rr=1.5,max_hold_seconds=28800,min_bb_bw_pctile=0.6,tf_scale=intraday,trigger_tf=M5 | 19 | -0.114 | -0.519..+0.295 | 0.83 | 4.8 | -0.550 (15) | +0.089 |
| legacy_momentum | **rejected** | rr=1.5,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 198 | -0.079 | -0.217..+0.059 | 0.87 | 24.7 | +0.058 (116) | +0.027 |
| legacy_rejection | **rejected** | rr=1.5,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 52 | -0.309 | -0.564..-0.047 | 0.57 | 19.0 | +0.334 (45) | +0.162 |

## Notes per setup

- **trend_pullback** (trend continuation): test expectancy -0.142R after costs is not positive. Rejected signals: structural stop too wide: 183, stop on the wrong side of entry: 2, position size below broker minimum: 3.
- **breakout** (breakout): test expectancy -0.036R after costs is not positive. Rejected signals: structural stop too wide: 27.
- **failed_breakout** (failed breakout): test expectancy -0.190R after costs is not positive. Rejected signals: bands too narrow: 13270, structural stop too wide: 3.
- **range_reversion** (range mean reversion): test expectancy -0.085R after costs is not positive. Rejected signals: bands too narrow: 13879, structural stop too wide: 5, structural stop too tight: 1.
- **liquidity_sweep** (liquidity sweep / market structure): 19 test trades < 30 required. Rejected signals: bands too narrow: 4628, structural stop too wide: 1.
- **legacy_momentum** (momentum continuation (incumbent)): test expectancy -0.079R after costs is not positive. Rejected signals: costs too large for the stop: 1.
- **legacy_rejection** (S/R rejection (incumbent)): test expectancy -0.309R after costs is not positive. Rejected signals: none.

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
