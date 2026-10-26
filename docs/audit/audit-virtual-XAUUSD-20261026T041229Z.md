# Trade audit: virtual

Filters: {'symbol': 'XAUUSD', 'style': 'scalp'}. Closed trades: 58.

Period: 2026-10-22T14:40:08.488000+00:00 to 2026-10-26T03:41:09.916000+00:00

## Headline (dashboard arithmetic)

- Trades 58: 30 wins / 28 losses, win rate 51.7%
- Pips: +1,587 / -1,920, net -333; PF (pips) 0.83
- Average win 52.9 pips, average loss 68.6 pips
- Money: net -74.29, PF (money) 0.94
- Trades whose pip sign and money sign differ: 0

## Outcomes in R

- Expectancy -0.03R, 90% CI (-0.23, 0.19)
- Average win 0.80R, average loss -0.93R
- Break-even win rate at this payoff 53.6%; observed 51.7%; P(win rate this low | break-even) = 0.440

### Exploration vs model-approved

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| exploration | 58 | 51.7% | -333 | -74.29 | -0.03 | 0.94 |

### Entry rule

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| momentum_continuation | 56 | 50.0% | -432 | -157.85 | -0.07 | 0.86 |
| rejection_resistance | 2 | 100.0% | 99 | 83.56 | 0.91 | n/a |

### Symbol

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| XAUUSD.sd | 58 | 51.7% | -333 | -74.29 | -0.03 | 0.94 |

### Style

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| scalp | 58 | 51.7% | -333 | -74.29 | -0.03 | 0.94 |

### Side

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| SELL | 32 | 59.4% | 128 | 208.64 | 0.13 | 1.41 |
| BUY | 26 | 42.3% | -461 | -282.94 | -0.24 | 0.57 |

### Exit reason

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| stop_loss | 22 | 0.0% | -1,710 | -1,076.23 | -1.08 | 0.00 |
| trailing_stop | 13 | 100.0% | 291 | 219.52 | 0.36 | n/a |
| take_profit | 12 | 100.0% | 1,184 | 797.54 | 1.48 | n/a |
| expiry | 11 | 45.5% | -98 | -15.12 | -0.05 | 0.84 |

### Regime at entry

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| ranging | 49 | 53.1% | -286 | -87.17 | -0.04 | 0.92 |
| trending_down | 9 | 44.4% | -47 | 12.88 | 0.01 | 1.09 |

### Entry hour (Dubai)

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| 02 | 6 | 66.7% | 107 | 92.73 | 0.38 | 1.97 |
| 18 | 5 | 40.0% | 71 | 62.54 | 0.25 | 1.93 |
| 04 | 5 | 20.0% | -249 | -125.28 | -0.54 | 0.37 |
| 05 | 5 | 20.0% | -210 | -147.07 | -0.59 | 0.29 |
| 09 | 5 | 60.0% | 3 | 7.61 | 0.04 | 1.08 |
| 20 | 4 | 25.0% | -193 | -144.39 | -0.76 | 0.05 |
| 06 | 4 | 50.0% | -76 | -18.29 | -0.11 | 0.80 |
| 21 | 3 | 66.7% | 24 | 17.91 | 0.13 | 2.62 |
| 22 | 3 | 100.0% | 120 | 100.71 | 0.72 | n/a |
| 23 | 3 | 66.7% | 45 | 47.78 | 0.41 | 2.95 |
| 00 | 3 | 33.3% | -83 | -85.58 | -0.81 | 0.08 |
| 03 | 3 | 100.0% | 141 | 119.93 | 0.85 | n/a |
| 19 | 2 | 50.0% | -34 | -6.51 | -0.11 | 0.59 |
| 07 | 2 | 100.0% | 55 | 25.72 | 0.28 | n/a |
| 10 | 2 | 0.0% | -118 | -67.32 | -0.71 | 0.00 |
| 17 | 2 | 50.0% | 35 | 21.07 | 0.14 | 1.45 |
| 08 | 1 | 100.0% | 30 | 24.16 | 0.53 | n/a |

### Strategy version

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| strat-f85f55f98f | 58 | 51.7% | -333 | -74.29 | -0.03 | 0.94 |

## Exits

- stop_loss: 22 trades, avg -1.08R, median hold 584 s, net -1,710 pips
- take_profit: 12 trades, avg 1.48R, median hold 957 s, net 1,184 pips
- trailing_stop: 13 trades, avg 0.36R, median hold 2,486 s, net 291 pips
- expiry: 11 trades, avg -0.05R, median hold 3,600 s, net -98 pips
- Stop-loss exits lost 1.08x the planned risk on average
- MFE/MAE: {'recorded_trades': 0, 'note': 'MFE/MAE and the initial stop were not stored for these trades'}

## Costs

- Spread 109.82, slippage 124.08, commission 0.00, swap -1.13; average cost 0.091R per trade
- Median stop distance 52.8 pips (some stops are the final (trailed) stop; the initial stop was not stored)

## Spacing

- Median gap after an exit 21 s; re-entries within 60 s: 39; within 5 min of a loss: 21

## Integrity

- Clean: True; issues: none
- Implied money per price unit per lot: {'XAUUSD.sd': {'min': 99.99999999999999, 'max': 100.00000000000001}}

