# Setup research — XAUUSD.sd (equiti)

Data: mt5,mt5_history, 62,184,629 ticks, 120,570 M1 bars, 2026-06-28T22:00:20.025000+00:00 → 2026-10-29T11:17:11.951000+00:00
Splits: train 2026-06-28T22:00 → 2026-08-29T04:38; validation 2026-08-29T04:38 → 2026-09-28T19:57; test 2026-09-28T19:57 → 2026-10-29T11:17
Data hash: `1b4cdc9ef050d5302418356dd655d1a0`

_historical research on recorded ticks with modelled costs — NOT live or forward results; a 'candidate' still needs walk-forward and forward virtual evidence; account loss stops (drawdown, daily/weekly loss, loss cooldowns) are off while measuring, per-trade rules apply_

| Setup | Verdict | Variant | Test trades | Test exp. (R) | 90% CI | PF | Max DD (R) | Random baseline (R) | Val. exp. (R) |
|---|---|---|---|---|---|---|---|---|---|
| trend_pullback | **rejected** | rr=1.5 | 364 | -0.097 | -0.195..+0.001 | 0.84 | 35.5 | -0.148 (305) | -0.143 |
| breakout | **rejected** | rr=1.5 | 187 | -0.038 | -0.169..+0.095 | 0.93 | 19.7 | -0.118 (154) | +0.035 |
| failed_breakout | **rejected** | rr=1.5 | 470 | -0.218 | -0.311..-0.127 | 0.70 | 106.7 | -0.197 (361) | -0.212 |
| range_reversion | **rejected** | rr=1.5 | 350 | -0.081 | -0.185..+0.030 | 0.87 | 41.7 | -0.189 (248) | -0.218 |
| liquidity_sweep | **rejected** | rr=1.5 | 241 | -0.289 | -0.406..-0.163 | 0.62 | 73.1 | -0.058 (206) | -0.062 |
| legacy_momentum | **rejected** | rr=2 | 477 | -0.122 | -0.207..-0.026 | 0.80 | 67.8 | -0.123 (304) | -0.032 |
| legacy_rejection | **inconclusive** | rr=2 | 367 | +0.016 | -0.086..+0.129 | 1.03 | 14.6 | -0.103 (247) | -0.151 |

## Notes per setup

- **trend_pullback** (trend continuation): test expectancy -0.097R after costs is not positive. Rejected signals: structural stop too tight: 92, costs too large for the stop: 144, structural stop too wide: 63, stop on the wrong side of entry: 4.
- **breakout** (breakout): test expectancy -0.038R after costs is not positive. Rejected signals: structural stop too wide: 27.
- **failed_breakout** (failed breakout): test expectancy -0.218R after costs is not positive. Rejected signals: costs too large for the stop: 301, structural stop too tight: 57, structural stop too wide: 37, position size below broker minimum: 24.
- **range_reversion** (range mean reversion): test expectancy -0.081R after costs is not positive. Rejected signals: costs too large for the stop: 102, structural stop too tight: 26, structural stop too wide: 14.
- **liquidity_sweep** (liquidity sweep / market structure): test expectancy -0.289R after costs is not positive. Rejected signals: costs too large for the stop: 251, structural stop too tight: 41, structural stop too wide: 1.
- **legacy_momentum** (momentum continuation (incumbent)): test expectancy -0.122R after costs is not positive. Rejected signals: costs too large for the stop: 23, position size below broker minimum: 4.
- **legacy_rejection** (S/R rejection (incumbent)): validation expectancy not positive. Rejected signals: costs too large for the stop: 4, position size below broker minimum: 6.

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
