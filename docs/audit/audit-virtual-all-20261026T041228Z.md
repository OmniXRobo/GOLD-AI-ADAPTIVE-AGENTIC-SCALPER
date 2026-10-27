# Trade audit: virtual

Filters: none. Closed trades: 226.

Period: 2026-10-22T14:40:08.488000+00:00 to 2026-10-26T03:46:20.231000+00:00

## Headline (dashboard arithmetic)

- Trades 226: 89 wins / 137 losses, win rate 39.4%
- Pips: +8,840 / -15,005, net -6,165; PF (pips) 0.59
- Average win 99.3 pips, average loss 109.5 pips
- Money: net -761.63, PF (money) 0.71
- Trades whose pip sign and money sign differ: 0

## Outcomes in R

- Expectancy -0.29R, 90% CI (-0.4, -0.17)
- Average win 0.88R, average loss -1.05R
- Break-even win rate at this payoff 54.3%; observed 39.4%; P(win rate this low | break-even) = 0.000

### Exploration vs model-approved

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| exploration | 226 | 39.4% | -6,165 | -761.63 | -0.29 | 0.71 |

### Entry rule

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| momentum_continuation | 219 | 39.3% | -6,016 | -816.44 | -0.29 | 0.68 |
| rejection_resistance | 4 | 50.0% | -13 | 68.40 | -0.24 | 5.51 |
| rejection_support | 3 | 33.3% | -136 | -13.59 | -0.44 | 0.48 |

### Symbol

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| BTCUSD.lv | 129 | 41.1% | -5,655 | -536.06 | -0.26 | 0.57 |
| XAUUSD.sd | 58 | 51.7% | -333 | -74.29 | -0.03 | 0.94 |
| NZDUSD.sd | 10 | 10.0% | -37 | -37.12 | -0.74 | 0.02 |
| AUDUSD.sd | 8 | 12.5% | -32 | -31.74 | -0.85 | 0.01 |
| USDJPY.sd | 8 | 12.5% | -75 | -49.67 | -1.05 | 0.03 |
| EURUSD.sd | 4 | 0.0% | -16 | -15.90 | -1.06 | 0.00 |
| USDCAD.sd | 3 | 33.3% | -10 | -7.28 | -0.35 | 0.25 |
| GBPUSD.sd | 3 | 66.7% | -2 | -1.70 | -0.14 | 0.62 |
| USDCHF.sd | 3 | 0.0% | -7 | -7.88 | -0.66 | 0.00 |

### Style

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| scalp | 214 | 40.2% | -3,399 | -503.67 | -0.27 | 0.77 |
| swing | 12 | 25.0% | -2,766 | -257.96 | -0.53 | 0.35 |

### Side

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| SELL | 129 | 46.5% | -1,428 | -8.96 | -0.14 | 0.99 |
| BUY | 97 | 29.9% | -4,737 | -752.67 | -0.49 | 0.42 |

### Exit reason

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| stop_loss | 111 | 0.0% | -14,597 | -2,438.00 | -1.19 | 0.00 |
| take_profit | 46 | 100.0% | 6,786 | 1,357.76 | 1.36 | n/a |
| expiry | 40 | 35.0% | 177 | -20.65 | -0.13 | 0.86 |
| trailing_stop | 29 | 100.0% | 1,469 | 339.27 | 0.34 | n/a |

### Regime at entry

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| ranging | 190 | 39.5% | -4,821 | -641.71 | -0.29 | 0.70 |
| trending_down | 28 | 42.9% | -1,145 | -92.17 | -0.18 | 0.75 |
| trending_up | 8 | 25.0% | -200 | -27.75 | -0.66 | 0.50 |

### Entry hour (Dubai)

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| 18 | 22 | 59.1% | 1,169 | 171.92 | 0.33 | 2.07 |
| 03 | 19 | 47.4% | -6 | 93.71 | -0.16 | 1.61 |
| 02 | 18 | 55.6% | 518 | 107.85 | 0.09 | 1.71 |
| 22 | 16 | 50.0% | 587 | 133.09 | 0.17 | 7.72 |
| 23 | 14 | 35.7% | -23 | 18.19 | -0.37 | 1.31 |
| 00 | 14 | 21.4% | -410 | -144.43 | -1.04 | 0.13 |
| 05 | 13 | 30.8% | -814 | -212.11 | -0.38 | 0.35 |
| 06 | 13 | 15.4% | -625 | -83.04 | -0.65 | 0.48 |
| 04 | 12 | 41.7% | -287 | -137.54 | -0.41 | 0.41 |
| 09 | 10 | 70.0% | 149 | 22.27 | 0.35 | 1.22 |
| 07 | 8 | 25.0% | -586 | -42.14 | -0.84 | 0.38 |
| 13 | 8 | 25.0% | -806 | -80.58 | -0.55 | 0.19 |
| 19 | 7 | 28.6% | -722 | -75.31 | -0.64 | 0.21 |
| 20 | 7 | 28.6% | -915 | -211.87 | -0.60 | 0.13 |
| 17 | 7 | 42.9% | -71 | 10.42 | -0.10 | 1.13 |
| 21 | 6 | 33.3% | -1,113 | -90.12 | -0.49 | 0.24 |
| 10 | 6 | 16.7% | -347 | -90.20 | -0.56 | 0.11 |
| 01 | 6 | 50.0% | 66 | 6.63 | -0.13 | 1.20 |
| 12 | 5 | 40.0% | -152 | -15.22 | -0.24 | 0.52 |
| 15 | 5 | 20.0% | -758 | -75.76 | -0.94 | 0.02 |
| 08 | 4 | 50.0% | -674 | -32.77 | -0.28 | 0.49 |
| 11 | 4 | 0.0% | -317 | -31.67 | -0.96 | 0.00 |
| 16 | 1 | 100.0% | 63 | 6.28 | 0.53 | n/a |
| 14 | 1 | 0.0% | -92 | -9.24 | -1.23 | 0.00 |

### Strategy version

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| strat-f85f55f98f | 214 | 40.2% | -3,399 | -503.67 | -0.27 | 0.77 |
| strat-0c5bd67174 | 12 | 25.0% | -2,766 | -257.96 | -0.53 | 0.35 |

## Exits

- stop_loss: 111 trades, avg -1.19R, median hold 1,007 s, net -14,597 pips
- take_profit: 46 trades, avg 1.36R, median hold 599 s, net 6,786 pips
- trailing_stop: 29 trades, avg 0.34R, median hold 2,097 s, net 1,469 pips
- expiry: 40 trades, avg -0.13R, median hold 3,601 s, net 177 pips
- Stop-loss exits lost 1.19x the planned risk on average
- MFE/MAE: {'recorded_trades': 0, 'note': 'MFE/MAE and the initial stop were not stored for these trades'}

## Costs

- Spread 228.81, slippage 400.40, commission 0.00, swap -3.28; average cost 0.236R per trade
- Median stop distance 67.4 pips (some stops are the final (trailed) stop; the initial stop was not stored)

## Spacing

- Median gap after an exit 108 s; re-entries within 60 s: 85; within 5 min of a loss: 66

## Integrity

- Clean: True; issues: none
- Implied money per price unit per lot: {'XAUUSD.sd': {'min': 99.99999999999999, 'max': 100.00000000000001}, 'USDCAD.sd': {'min': 71372.49304118192, 'max': 71372.49304118194}, 'AUDUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'GBPUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'USDCHF.sd': {'min': 121165.12383075654, 'max': 121165.12383075655}, 'USDJPY.sd': {'min': 637.364878645727, 'max': 637.5274136787883}, 'EURUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'NZDUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'BTCUSD.lv': {'min': 1.0, 'max': 1.0}}

