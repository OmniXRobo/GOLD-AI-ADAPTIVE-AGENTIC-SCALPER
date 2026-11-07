# Regime benchmark (M5, 25170 bars, horizon 12 bars)

Period 2026-06-28T22:00:00+00:00 → 2026-11-04T06:10:00+00:00. Splits (bars): {'train': 12585, 'validation': 6292, 'test': 6293}.
**Verdict: hmm_better_than_rule** · uncertainty helps: True

HMM states: quiet, ranging, ranging, volatile (11 EM iterations). Samples: {'train': 1044, 'validation': 524, 'test': 523}.

| Method | Split | Samples | Future-vol R² | Trend calls | Trend hit rate | z |
|---|---|---|---|---|---|---|
| rule | validation | 524 | 0.0148 | 123 | 0.512 | 0.27 |
| rule | test | 523 | -0.0624 | 100 | 0.500 | 0.0 |
| hmm | validation | 524 | 0.151 | 0 | - | None |
| hmm | test | 523 | 0.1136 | 0 | - | None |
| random | validation | 524 | -0.001 | 0 | - | None |
| random | test | 523 | -0.12 | 0 | - | None |

| Split | Certain | Uncertain | Certain share | Abs err certain | Abs err uncertain |
|---|---|---|---|---|---|
| validation | 483 | 41 | 0.922 | 0.2966 | 0.3863 |
| test | 477 | 46 | 0.912 | 0.3394 | 0.3596 |

Notes:
- uncertainty flag separates better from worse readings on validation and test

Research only: no live engine uses the regime agent until this benchmark passes on real ticks.
