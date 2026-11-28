# Setup research — XAUUSD.sd (equiti)

Data: mt5, 9,727,017 ticks, 12,228 M1 bars, 2026-10-29T11:17:12.024000+00:00 → 2026-11-27T19:44:59.149000+00:00
Splits: train 2026-10-29T11:17 → 2026-11-13T03:31; validation 2026-11-13T03:31 → 2026-11-20T11:38; test 2026-11-20T11:38 → 2026-11-27T19:44
Data hash: `36817322ede6a42a0778e82c480c3312`

_historical research on recorded ticks with modelled costs — NOT live or forward results; a 'candidate' still needs walk-forward and forward virtual evidence; account loss stops (drawdown, daily/weekly loss, loss cooldowns) are off while measuring, per-trade rules apply_

| Setup | Verdict | Variant | Test trades | Test exp. (R) | 90% CI | PF | Max DD (R) | Random baseline (R) | Val. exp. (R) |
|---|---|---|---|---|---|---|---|---|---|
| failed_breakout | **inconclusive** | rr=2,max_hold_seconds=28800,tf_scale=intraday,trigger_tf=M5 | 15 | +0.264 | -0.310..+0.886 | 1.48 | 3.1 | +0.188 (13) | +0.613 |
| legacy_momentum | **inconclusive** | rr=2,max_hold_seconds=14400,tf_scale=intraday,trail_distance_r=0.75,trail_start_r=1.0 | 62 | +0.185 | -0.061..+0.429 | 1.43 | 5.3 | +0.096 (33) | -0.646 |

## Notes per setup

- **failed_breakout** (failed breakout): fewer than 10 validation trades for every variant; chosen on train; 90% interval -0.310..+0.886R includes zero. Rejected signals: structural stop too wide: 2.
- **legacy_momentum** (momentum continuation (incumbent)): fewer than 10 validation trades for every variant; chosen on train; validation expectancy not positive. Rejected signals: position size below broker minimum: 18.
