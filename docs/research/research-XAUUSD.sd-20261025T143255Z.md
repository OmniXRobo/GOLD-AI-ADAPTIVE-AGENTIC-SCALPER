# Setup research — XAUUSD.sd (equiti)

Data: mt5,mt5_history, 3,285,567 ticks, 6,897 M1 bars, 2026-10-18T22:00:20.015000+00:00 → 2026-10-23T20:56:59.628000+00:00
Splits: train 2026-10-18T22:00 → 2026-10-21T09:28; validation 2026-10-21T09:28 → 2026-10-22T15:12; test 2026-10-22T15:12 → 2026-10-23T20:56
Data hash: `f0c5b3892fe97c867f1f0749a21fe103`

_historical research on recorded ticks with modelled costs — NOT live or forward results; a 'candidate' still needs walk-forward and forward virtual evidence_

| Setup | Verdict | RR | Test trades | Test exp. (R) | 90% CI | PF | Max DD (R) | Random baseline (R) | Val. exp. (R) |
|---|---|---|---|---|---|---|---|---|---|
| trend_pullback | **insufficient_data** | 1.5 | 11 | -0.346 | -0.804..+0.141 | 0.49 | 7.1 | +0.000 (0) | +0.173 |
| breakout | **insufficient_data** | 1.0 | 0 | +0.000 | n/a | n/a | 0.0 | +0.000 (0) | +0.000 |
| failed_breakout | **insufficient_data** | 2.0 | 9 | -0.871 | -1.096..-0.449 | 0.10 | 7.8 | +0.000 (0) | -0.479 |
| range_reversion | **insufficient_data** | 1.5 | 11 | -0.143 | -0.643..+0.527 | 0.79 | 3.9 | -0.562 (12) | -0.456 |
| liquidity_sweep | **insufficient_data** | 2.0 | 10 | -0.207 | -0.821..+0.426 | 0.73 | 3.6 | +0.061 (12) | -0.026 |
| legacy_momentum | **insufficient_data** | 1.5 | 10 | -0.513 | -0.911..-0.024 | 0.29 | 5.1 | +0.413 (9) | +0.299 |
| legacy_rejection | **insufficient_data** | 2.0 | 11 | +0.908 | +0.271..+1.506 | 4.25 | 2.0 | -0.367 (8) | -0.444 |

## Notes per setup

- **trend_pullback** (trend continuation): 11 test trades < 30 required; test trades cover a single regime. Rejected signals: costs too large for the stop: 14, structural stop too tight: 6.
- **breakout** (breakout): fewer than 10 validation trades for every variant; chosen on train; 0 test trades < 30 required. Rejected signals: structural stop too wide: 1.
- **failed_breakout** (failed breakout): 9 test trades < 30 required; test trades cover a single regime. Rejected signals: costs too large for the stop: 21, structural stop too tight: 3.
- **range_reversion** (range mean reversion): 11 test trades < 30 required. Rejected signals: costs too large for the stop: 15.
- **liquidity_sweep** (liquidity sweep / market structure): 10 test trades < 30 required. Rejected signals: costs too large for the stop: 23, structural stop too tight: 2.
- **legacy_momentum** (momentum continuation (incumbent)): 10 test trades < 30 required; test trades cover a single regime. Rejected signals: costs too large for the stop: 2.
- **legacy_rejection** (S/R rejection (incumbent)): 11 test trades < 30 required. Rejected signals: none.

## Feature evaluation

Rows: 1187 (train 510, validation 345). bracket 1.0xATR(M5) stop, 1.5R target, 60 M1 bars, after slippage; bar-level approximation for ranking features only

| Feature | ρ long train | ρ long val | ρ short train | ρ short val | Informative | Redundant with | Kept |
|---|---|---|---|---|---|---|---|
| ema20_m5_dist | -0.042 | -0.023 | +0.146 | +0.019 | no | rsi_m5, bb_pctb_m5, swing_high_dist, swing_low_dist | no |
| ema50_m15_slope | +0.115 | -0.172 | +0.244 | -0.217 | no | — | no |
| adx_m15 | -0.070 | +0.204 | +0.060 | +0.334 | no | — | no |
| di_diff_m15 | -0.032 | -0.197 | +0.147 | -0.138 | no | — | no |
| rsi_m5 | -0.053 | -0.063 | +0.171 | +0.006 | no | ema20_m5_dist, bb_pctb_m5, swing_low_dist | no |
| macd_hist_m5 | -0.039 | -0.064 | +0.053 | +0.101 | no | bb_pctb_m5, swing_low_dist | no |
| bb_pctb_m5 | -0.056 | -0.035 | +0.136 | +0.049 | no | ema20_m5_dist, rsi_m5, macd_hist_m5, swing_low_dist | no |
| bb_bw_pctile_m5 | +0.352 | +0.328 | +0.180 | +0.047 | yes | — | yes |
| vwap_dist | +0.172 | -0.182 | +0.265 | -0.223 | no | — | no |
| poc_dist | -0.057 | -0.044 | +0.257 | -0.035 | no | — | no |
| swing_high_dist | +0.017 | -0.081 | -0.168 | +0.026 | no | ema20_m5_dist | no |
| swing_low_dist | -0.065 | +0.091 | +0.071 | +0.050 | no | ema20_m5_dist, rsi_m5, macd_hist_m5, bb_pctb_m5 | no |
| mom_m5_3 | +0.006 | +0.086 | +0.123 | -0.035 | no | — | no |
| efficiency_m5 | +0.014 | -0.085 | -0.108 | +0.032 | no | — | no |
| spread_atr | -0.557 | -0.583 | -0.385 | -0.233 | yes | — | yes |
| tick_rate_z | +0.008 | -0.121 | -0.020 | +0.046 | no | — | no |

Kept features: bb_bw_pctile_m5, spread_atr
