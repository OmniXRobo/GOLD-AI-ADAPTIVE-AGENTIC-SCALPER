# Trade audit: virtual

Filters: {'broker': 'equiti', 'since': '2026-10-26'}. Closed trades: 686.

Period: 2026-10-26T00:01:01.237000+00:00 to 2026-11-03T02:08:00.743000+00:00

## Headline (dashboard arithmetic)

- Trades 686: 254 wins / 432 losses, win rate 37.0%
- Pips: +14,045 / -23,926, net -9,882; PF (pips) 0.59
- Average win 55.3 pips, average loss 55.4 pips
- Money: net -2,625.70, PF (money) 0.62
- Trades whose pip sign and money sign differ: 1

## Outcomes in R

- Expectancy -0.30R, 90% CI (-0.36, -0.23)
- Average win 0.87R, average loss -0.98R
- Break-even win rate at this payoff 53.1%; observed 37.0%; P(win rate this low | break-even) = 0.000

### Exploration vs model-approved

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| exploration | 677 | 36.8% | -9,973 | -2,669.51 | -0.30 | 0.60 |
| model-approved | 9 | 55.6% | 91 | 43.81 | 0.18 | 1.22 |

### Entry rule

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| rejection_support | 258 | 35.7% | -2,912 | -1,067.34 | -0.34 | 0.58 |
| rejection_resistance | 249 | 41.8% | 4 | -404.75 | -0.22 | 0.77 |
| momentum_continuation | 147 | 34.7% | -4,787 | -618.04 | -0.33 | 0.60 |
| rule:failed_breakout | 15 | 26.7% | -1,119 | -221.83 | -0.33 | 0.54 |
| rule:trend_pullback | 11 | 9.1% | -1,106 | -331.82 | -0.76 | 0.16 |
| rule:breakout | 6 | 33.3% | 38 | 18.08 | 0.11 | 1.13 |

### Symbol

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| XAUUSD.sd | 139 | 40.3% | -3,665 | -1,048.96 | -0.17 | 0.70 |
| BTCUSD.lv | 87 | 39.1% | -5,124 | -546.04 | -0.26 | 0.58 |
| USDJPY.sd | 86 | 45.3% | -114 | -72.45 | -0.18 | 0.76 |
| AUDUSD.sd | 81 | 35.8% | -129 | -129.78 | -0.31 | 0.52 |
| NZDUSD.sd | 69 | 27.5% | -152 | -152.10 | -0.50 | 0.41 |
| USDCHF.sd | 64 | 40.6% | -131 | -158.38 | -0.26 | 0.53 |
| EURUSD.sd | 60 | 36.7% | -110 | -109.79 | -0.29 | 0.61 |
| GBPUSD.sd | 55 | 25.5% | -280 | -280.80 | -0.53 | 0.33 |
| USDCAD.sd | 45 | 33.3% | -177 | -127.41 | -0.43 | 0.37 |

### Style

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| scalp | 583 | 37.7% | -4,654 | -1,507.02 | -0.29 | 0.68 |
| swing | 71 | 38.0% | -3,042 | -583.11 | -0.27 | 0.50 |
| research | 32 | 21.9% | -2,186 | -535.57 | -0.40 | 0.48 |

### Side

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| BUY | 354 | 34.2% | -6,489 | -1,810.40 | -0.35 | 0.55 |
| SELL | 332 | 40.1% | -3,392 | -815.30 | -0.24 | 0.71 |

### Exit reason

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| stop_loss | 345 | 0.0% | -22,459 | -6,361.49 | -1.12 | 0.00 |
| expiry | 145 | 40.0% | -315 | -128.66 | -0.04 | 0.74 |
| take_profit | 108 | 100.0% | 10,862 | 3,258.42 | 1.50 | n/a |
| trailing_stop | 88 | 100.0% | 2,031 | 606.03 | 0.33 | n/a |

### Regime at entry

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| ranging | 486 | 36.6% | -8,722 | -1,996.65 | -0.32 | 0.60 |
| trending_down | 109 | 34.9% | -1,335 | -398.94 | -0.30 | 0.63 |
| trending_up | 90 | 42.2% | 184 | -221.71 | -0.16 | 0.72 |
| quiet | 1 | 0.0% | -8 | -8.40 | -1.15 | 0.00 |

### Entry hour (Dubai)

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| 17 | 55 | 40.0% | -1,807 | -331.23 | -0.27 | 0.49 |
| 12 | 49 | 42.9% | -764 | -180.06 | -0.26 | 0.57 |
| 11 | 46 | 39.1% | -601 | -180.23 | -0.34 | 0.61 |
| 10 | 45 | 37.8% | -317 | -84.64 | -0.34 | 0.72 |
| 16 | 41 | 36.6% | -483 | -102.64 | -0.35 | 0.73 |
| 18 | 40 | 37.5% | 88 | -183.20 | -0.26 | 0.57 |
| 15 | 37 | 37.8% | -279 | -60.03 | -0.32 | 0.82 |
| 05 | 35 | 37.1% | -733 | -196.49 | -0.37 | 0.53 |
| 00 | 35 | 25.7% | -1,669 | -270.03 | -0.61 | 0.30 |
| 04 | 34 | 50.0% | -330 | -133.90 | -0.12 | 0.72 |
| 13 | 32 | 25.0% | -818 | -173.01 | -0.40 | 0.41 |
| 19 | 29 | 27.6% | -543 | -149.04 | -0.38 | 0.39 |
| 14 | 25 | 32.0% | -815 | -93.26 | -0.35 | 0.55 |
| 20 | 24 | 33.3% | 195 | -101.98 | -0.31 | 0.62 |
| 23 | 23 | 30.4% | 1,017 | -125.33 | -0.28 | 0.52 |
| 09 | 22 | 36.4% | -454 | -159.55 | -0.46 | 0.42 |
| 21 | 22 | 31.8% | -429 | -74.98 | -0.35 | 0.67 |
| 22 | 22 | 54.5% | 261 | -51.04 | -0.15 | 0.68 |
| 06 | 20 | 25.0% | 169 | 91.29 | -0.03 | 1.64 |
| 07 | 17 | 41.2% | 46 | -71.86 | 0.01 | 0.58 |
| 03 | 15 | 26.7% | -885 | -112.40 | -0.48 | 0.41 |
| 08 | 14 | 71.4% | -81 | 137.70 | 0.44 | 2.14 |
| 01 | 2 | 0.0% | -691 | -60.30 | -1.11 | 0.00 |
| 02 | 2 | 50.0% | 39 | 40.55 | 0.31 | 23.07 |

### Strategy version

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| strat-1c937ed400 | 444 | 39.0% | -2,688 | -1,111.91 | -0.27 | 0.68 |
| strat-f85f55f98f | 139 | 33.8% | -1,966 | -395.11 | -0.37 | 0.68 |
| strat-a290cf732c | 53 | 39.6% | -175 | -322.27 | -0.26 | 0.59 |
| strat-0c5bd67174 | 18 | 33.3% | -2,866 | -260.83 | -0.28 | 0.30 |
| rule-failed_breakout-0f3a97a6 | 15 | 26.7% | -1,119 | -221.83 | -0.33 | 0.54 |
| rule-trend_pullback-acf3f57d | 11 | 9.1% | -1,106 | -331.82 | -0.76 | 0.16 |
| rule-breakout-8d54bf35 | 6 | 33.3% | 38 | 18.08 | 0.11 | 1.13 |

## Exits

- stop_loss: 345 trades, avg -1.12R, median hold 1,147 s, net -22,459 pips
- take_profit: 108 trades, avg 1.50R, median hold 1,807 s, net 10,862 pips
- trailing_stop: 88 trades, avg 0.33R, median hold 2,216 s, net 2,031 pips
- expiry: 145 trades, avg -0.04R, median hold 3,601 s, net -315 pips
- Stop-loss exits lost 1.12x the planned risk on average
- MFE/MAE: {'recorded_trades': 668, 'losers_that_reached_+0.5R': 80, 'losers_that_reached_+1R': 6, 'avg_winner_mfe_r': 1.2791431756940759, 'avg_winner_realized_r': 0.8676641561216838, 'avg_mae_r': -0.7659681672386702}

## Costs

- Spread 916.56, slippage 795.88, commission 0.00, swap -4.77; average cost 0.265R per trade
- Median stop distance 9.7 pips (some stops are the final (trailed) stop; the initial stop was not stored)

## Spacing

- Median gap after an exit 1,980 s; re-entries within 60 s: 38; within 5 min of a loss: 6

## Integrity

- Clean: False; issues: {'overlapping_positions': [['538ccbe13f5949fdbfa66443d00c72de', '3d3a238d6b3d48ce957a6f97b8719a27'], ['d53e486cc88644a2aa557219695b2abf', 'b73ec723e2ca475c89ca792c97387d5c'], ['89172136edef47d3aa28b7dc7f18cd98', '9cec09bedf9948c3b167726651b17d41'], ['9cec09bedf9948c3b167726651b17d41', 'b013ddfc69ac40839937e6f20783d5f7'], ['b013ddfc69ac40839937e6f20783d5f7', '15a370ef26bd4a9183d5d15822fea821'], ['9d4d5f51ebaf4d98915e00dd86b55e50', 'c3bb4ec671ea4478951f770c65b5a740'], ['48cb10f5e5c2409485c6850f4bab092b', 'e9b028651d694c9e856f67b9d21f769b'], ['6111018bf1714f638dedd999edf05f7c', '75ff1ef2add34dd1b40bb78e33049775'], ['75ff1ef2add34dd1b40bb78e33049775', '6f76f439529340fbbba7141e44f6952a']]}
- Implied money per price unit per lot: {'BTCUSD.lv': {'min': 1.0, 'max': 1.0}, 'XAUUSD.sd': {'min': 99.99999999999999, 'max': 100.00000000000001}, 'USDJPY.sd': {'min': 632.9794977940663, 'max': 637.5274136787882}, 'NZDUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'AUDUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'USDCHF.sd': {'min': 120748.15557192362, 'max': 121376.89954847796}, 'EURUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'GBPUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'USDCAD.sd': {'min': 71181.97672349362, 'max': 71533.82834742551}}

