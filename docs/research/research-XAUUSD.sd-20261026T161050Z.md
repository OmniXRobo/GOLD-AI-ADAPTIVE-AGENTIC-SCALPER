# Setup research — XAUUSD.sd (equiti)

Data: mt5,mt5_history, 13,172,823 ticks, 28,888 M1 bars, 2026-09-25T16:02:36.071000+00:00 → 2026-10-26T14:44:16.979000+00:00
Splits: train 2026-09-25T16:02 → 2026-10-11T03:23; validation 2026-10-11T03:23 → 2026-10-18T21:03; test 2026-10-18T21:03 → 2026-10-26T14:44
Data hash: `44289c53c5a284ae53e3ea8d49c56106`

_historical research on recorded ticks with modelled costs — NOT live or forward results; a 'candidate' still needs walk-forward and forward virtual evidence_

| Setup | Verdict | Variant | Test trades | Test exp. (R) | 90% CI | PF | Max DD (R) | Random baseline (R) | Val. exp. (R) |
|---|---|---|---|---|---|---|---|---|---|
| trend_pullback | **insufficient_data** | rr=1.5,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 16 | +0.196 | -0.222..+0.654 | 1.47 | 3.0 | -0.331 (7) | -0.258 |
| breakout | **insufficient_data** | rr=2,max_hold_seconds=14400,tf_scale=intraday | 12 | +0.095 | -0.483..+0.702 | 1.18 | 4.3 | +0.173 (5) | -1.020 |
| failed_breakout | **insufficient_data** | rr=1.5,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 22 | +0.041 | -0.351..+0.468 | 1.08 | 6.2 | -0.334 (17) | +0.013 |
| range_reversion | **insufficient_data** | rr=1.5,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 17 | -0.195 | -0.639..+0.296 | 0.71 | 5.3 | +0.250 (13) | -0.129 |
| liquidity_sweep | **insufficient_data** | rr=2,max_hold_seconds=14400,tf_scale=intraday | 23 | -0.535 | -0.921..-0.140 | 0.39 | 16.2 | +0.417 (14) | -0.628 |

## Notes per setup

- **trend_pullback** (trend continuation): 16 test trades < 30 required. Rejected signals: structural stop too wide: 22.
- **breakout** (breakout): fewer than 10 validation trades for every variant; chosen on train; 12 test trades < 30 required. Rejected signals: structural stop too wide: 3.
- **failed_breakout** (failed breakout): 22 test trades < 30 required. Rejected signals: structural stop too wide: 3.
- **range_reversion** (range mean reversion): 17 test trades < 30 required. Rejected signals: structural stop too wide: 4.
- **liquidity_sweep** (liquidity sweep / market structure): 23 test trades < 30 required. Rejected signals: structural stop too tight: 2.

## Feature evaluation

Rows: 5587 (train 2639, validation 1380). bracket 1.0xATR(M5) stop, 1.5R target, 60 M1 bars, after slippage; bar-level approximation for ranking features only

| Feature | ρ long train | ρ long val | ρ short train | ρ short val | Informative | Redundant with | Kept |
|---|---|---|---|---|---|---|---|
| ema20_m5_dist | -0.005 | +0.045 | -0.081 | +0.058 | no | rsi_m5, bb_pctb_m5, poc_dist, swing_high_dist, swing_low_dist | no |
| ema50_m15_slope | -0.066 | +0.016 | -0.099 | +0.125 | no | di_diff_m15, vwap_dist | no |
| adx_m15 | +0.005 | -0.002 | +0.040 | -0.010 | no | — | no |
| di_diff_m15 | -0.065 | -0.015 | -0.074 | +0.106 | no | ema50_m15_slope | no |
| rsi_m5 | -0.016 | +0.014 | -0.075 | +0.067 | no | ema20_m5_dist, bb_pctb_m5, poc_dist | no |
| macd_hist_m5 | +0.042 | +0.085 | +0.013 | +0.045 | yes | — | yes |
| bb_pctb_m5 | +0.005 | +0.037 | -0.043 | +0.057 | no | ema20_m5_dist, rsi_m5, swing_high_dist, swing_low_dist | no |
| bb_bw_pctile_m5 | +0.261 | +0.307 | +0.291 | +0.279 | yes | — | yes |
| vwap_dist | -0.022 | +0.055 | -0.112 | +0.162 | no | ema50_m15_slope | no |
| poc_dist | +0.005 | -0.028 | -0.035 | +0.067 | no | ema20_m5_dist, rsi_m5 | no |
| swing_high_dist | -0.009 | -0.070 | +0.048 | -0.045 | no | ema20_m5_dist, bb_pctb_m5 | no |
| swing_low_dist | +0.014 | +0.071 | -0.057 | +0.107 | no | ema20_m5_dist, bb_pctb_m5 | no |
| mom_m5_3 | -0.013 | +0.048 | -0.003 | -0.006 | no | — | no |
| efficiency_m5 | +0.025 | +0.025 | +0.055 | -0.018 | no | — | no |
| spread_atr | -0.443 | -0.524 | -0.472 | -0.373 | yes | — | yes |
| tick_rate_z | -0.017 | -0.100 | -0.021 | -0.056 | no | — | no |

Kept features: macd_hist_m5, bb_bw_pctile_m5, spread_atr
