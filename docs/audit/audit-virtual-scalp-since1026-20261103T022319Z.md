# Trade audit: virtual

Filters: {'broker': 'equiti', 'style': 'scalp', 'since': '2026-10-26'}. Closed trades: 583.

Period: 2026-10-26T00:01:01.237000+00:00 to 2026-11-03T02:08:00.743000+00:00

## Headline (dashboard arithmetic)

- Trades 583: 220 wins / 363 losses, win rate 37.7%
- Pips: +9,342 / -13,996, net -4,654; PF (pips) 0.67
- Average win 42.5 pips, average loss 38.6 pips
- Money: net -1,507.02, PF (money) 0.68
- Trades whose pip sign and money sign differ: 0

## Outcomes in R

- Expectancy -0.29R, 90% CI (-0.36, -0.23)
- Average win 0.83R, average loss -0.98R
- Break-even win rate at this payoff 54.0%; observed 37.7%; P(win rate this low | break-even) = 0.000

### Exploration vs model-approved

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| exploration | 574 | 37.5% | -4,745 | -1,550.84 | -0.30 | 0.65 |
| model-approved | 9 | 55.6% | 91 | 43.81 | 0.18 | 1.22 |

### Entry rule

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| rejection_resistance | 227 | 41.9% | 754 | -265.43 | -0.22 | 0.82 |
| rejection_support | 227 | 35.2% | -3,487 | -884.39 | -0.35 | 0.57 |
| momentum_continuation | 129 | 34.9% | -1,921 | -357.21 | -0.34 | 0.70 |

### Symbol

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| XAUUSD.sd | 97 | 47.4% | -668 | -317.73 | -0.06 | 0.86 |
| USDJPY.sd | 80 | 45.0% | -124 | -80.27 | -0.18 | 0.68 |
| AUDUSD.sd | 76 | 35.5% | -136 | -135.69 | -0.34 | 0.44 |
| BTCUSD.lv | 75 | 40.0% | -3,043 | -307.82 | -0.24 | 0.66 |
| NZDUSD.sd | 64 | 25.0% | -172 | -172.40 | -0.56 | 0.26 |
| USDCHF.sd | 56 | 42.9% | -73 | -88.75 | -0.23 | 0.61 |
| EURUSD.sd | 52 | 34.6% | -116 | -115.91 | -0.35 | 0.46 |
| GBPUSD.sd | 45 | 24.4% | -207 | -207.27 | -0.56 | 0.25 |
| USDCAD.sd | 38 | 31.6% | -114 | -81.18 | -0.43 | 0.43 |

### Style

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| scalp | 583 | 37.7% | -4,654 | -1,507.02 | -0.29 | 0.68 |

### Side

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| BUY | 292 | 34.9% | -4,286 | -1,016.32 | -0.35 | 0.62 |
| SELL | 291 | 40.5% | -368 | -490.70 | -0.24 | 0.76 |

### Exit reason

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| stop_loss | 282 | 0.0% | -13,233 | -4,311.52 | -1.14 | 0.00 |
| expiry | 138 | 41.3% | 321 | -43.93 | -0.04 | 0.88 |
| take_profit | 93 | 100.0% | 7,386 | 2,424.03 | 1.44 | n/a |
| trailing_stop | 70 | 100.0% | 873 | 424.40 | 0.29 | n/a |

### Regime at entry

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| ranging | 400 | 37.0% | -3,384 | -1,047.02 | -0.33 | 0.66 |
| trending_down | 99 | 35.4% | -1,864 | -326.32 | -0.29 | 0.64 |
| trending_up | 83 | 44.6% | 603 | -125.28 | -0.13 | 0.81 |
| quiet | 1 | 0.0% | -8 | -8.40 | -1.15 | 0.00 |

### Entry hour (Dubai)

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| 12 | 46 | 45.7% | -422 | -89.22 | -0.21 | 0.73 |
| 17 | 45 | 44.4% | -726 | -180.59 | -0.21 | 0.57 |
| 11 | 41 | 41.5% | -526 | -135.62 | -0.32 | 0.63 |
| 16 | 37 | 35.1% | -394 | -77.77 | -0.40 | 0.75 |
| 18 | 36 | 38.9% | 543 | -110.17 | -0.20 | 0.67 |
| 10 | 35 | 31.4% | -269 | -145.19 | -0.52 | 0.29 |
| 15 | 33 | 39.4% | -6 | 13.42 | -0.28 | 1.05 |
| 00 | 29 | 24.1% | -611 | -174.68 | -0.69 | 0.28 |
| 04 | 28 | 50.0% | -347 | -106.39 | -0.13 | 0.70 |
| 05 | 28 | 32.1% | -642 | -198.10 | -0.47 | 0.37 |
| 13 | 25 | 24.0% | -474 | -91.87 | -0.39 | 0.32 |
| 19 | 24 | 25.0% | -16 | -68.83 | -0.37 | 0.51 |
| 20 | 21 | 38.1% | 543 | 27.54 | -0.21 | 1.20 |
| 09 | 20 | 40.0% | -218 | -78.34 | -0.40 | 0.60 |
| 14 | 20 | 30.0% | -155 | -89.74 | -0.45 | 0.20 |
| 21 | 20 | 35.0% | -388 | -36.02 | -0.28 | 0.81 |
| 22 | 19 | 57.9% | -290 | -48.85 | -0.16 | 0.49 |
| 06 | 18 | 22.2% | 706 | 114.74 | -0.08 | 2.26 |
| 23 | 17 | 35.3% | -397 | -103.39 | -0.28 | 0.29 |
| 07 | 14 | 42.9% | 80 | -6.49 | 0.11 | 0.92 |
| 03 | 13 | 30.8% | -554 | -63.78 | -0.39 | 0.55 |
| 08 | 11 | 72.7% | -28 | 112.08 | 0.50 | 2.46 |
| 02 | 2 | 50.0% | 39 | 40.55 | 0.31 | 23.07 |
| 01 | 1 | 0.0% | -103 | -10.32 | -1.19 | 0.00 |

### Strategy version

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| strat-1c937ed400 | 444 | 39.0% | -2,688 | -1,111.91 | -0.27 | 0.68 |
| strat-f85f55f98f | 139 | 33.8% | -1,966 | -395.11 | -0.37 | 0.68 |

## Exits

- stop_loss: 282 trades, avg -1.14R, median hold 938 s, net -13,233 pips
- take_profit: 93 trades, avg 1.44R, median hold 1,601 s, net 7,386 pips
- trailing_stop: 70 trades, avg 0.29R, median hold 1,736 s, net 873 pips
- expiry: 138 trades, avg -0.04R, median hold 3,601 s, net 321 pips
- Stop-loss exits lost 1.14x the planned risk on average
- MFE/MAE: {'recorded_trades': 566, 'losers_that_reached_+0.5R': 58, 'losers_that_reached_+1R': 0, 'avg_winner_mfe_r': 1.2181308689514427, 'avg_winner_realized_r': 0.8299862169716257, 'avg_mae_r': -0.7645225840860304}

## Costs

- Spread 797.75, slippage 668.13, commission 0.00, swap -1.94; average cost 0.293R per trade
- Median stop distance 8.1 pips (some stops are the final (trailed) stop; the initial stop was not stored)

## Spacing

- Median gap after an exit 1,851 s; re-entries within 60 s: 28; within 5 min of a loss: 0

## Integrity

- Clean: True; issues: none
- Implied money per price unit per lot: {'BTCUSD.lv': {'min': 1.0, 'max': 1.0}, 'XAUUSD.sd': {'min': 99.99999999999999, 'max': 100.00000000000001}, 'USDJPY.sd': {'min': 632.9794977940663, 'max': 637.5274136787882}, 'AUDUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'NZDUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'EURUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'USDCHF.sd': {'min': 120748.15557192362, 'max': 121376.89954847796}, 'GBPUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'USDCAD.sd': {'min': 71181.97672349362, 'max': 71533.82834742551}}

