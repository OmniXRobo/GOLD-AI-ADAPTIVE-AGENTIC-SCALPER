# Trade audit: virtual

Filters: {'broker': 'equiti', 'style': 'research', 'since': '2026-10-26'}. Closed trades: 32.

Period: 2026-10-27T04:45:00.637000+00:00 to 2026-11-02T23:40:00.403000+00:00

## Headline (dashboard arithmetic)

- Trades 32: 7 wins / 25 losses, win rate 21.9%
- Pips: +963 / -3,150, net -2,186; PF (pips) 0.31
- Average win 137.6 pips, average loss 126.0 pips
- Money: net -535.57, PF (money) 0.48
- Trades whose pip sign and money sign differ: 0

## Outcomes in R

- Expectancy -0.40R, 90% CI (-0.69, -0.08)
- Average win 1.63R, average loss -0.96R
- Break-even win rate at this payoff 37.2%; observed 21.9%; P(win rate this low | break-even) = 0.050

### Exploration vs model-approved

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| exploration | 32 | 21.9% | -2,186 | -535.57 | -0.40 | 0.48 |

### Entry rule

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| rule:failed_breakout | 15 | 26.7% | -1,119 | -221.83 | -0.33 | 0.54 |
| rule:trend_pullback | 11 | 9.1% | -1,106 | -331.82 | -0.76 | 0.16 |
| rule:breakout | 6 | 33.3% | 38 | 18.08 | 0.11 | 1.13 |

### Symbol

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| XAUUSD.sd | 32 | 21.9% | -2,186 | -535.57 | -0.40 | 0.48 |

### Style

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| research | 32 | 21.9% | -2,186 | -535.57 | -0.40 | 0.48 |

### Side

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| BUY | 22 | 18.2% | -1,822 | -491.56 | -0.54 | 0.35 |
| SELL | 10 | 30.0% | -365 | -44.00 | -0.08 | 0.83 |

### Exit reason

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| stop_loss | 20 | 0.0% | -2,445 | -891.57 | -1.06 | 0.00 |
| take_profit | 7 | 100.0% | 963 | 484.73 | 1.63 | n/a |
| expiry | 5 | 0.0% | -705 | -128.73 | -0.59 | 0.00 |

### Regime at entry

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| ranging | 28 | 25.0% | -1,640 | -410.87 | -0.36 | 0.54 |
| trending_up | 2 | 0.0% | -388 | -77.15 | -0.83 | 0.00 |
| trending_down | 2 | 0.0% | -159 | -47.55 | -0.52 | 0.00 |

### Entry hour (Dubai)

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| 23 | 4 | 0.0% | -263 | -96.93 | -0.67 | 0.00 |
| 13 | 3 | 33.3% | -137 | -24.76 | -0.18 | 0.73 |
| 04 | 3 | 33.3% | 12 | -28.57 | -0.07 | 0.73 |
| 11 | 2 | 50.0% | -35 | -2.85 | 0.24 | 0.94 |
| 17 | 2 | 50.0% | 78 | 31.40 | 0.39 | 1.67 |
| 05 | 2 | 50.0% | 61 | 38.22 | 0.45 | 1.92 |
| 00 | 2 | 0.0% | -426 | -68.82 | -0.74 | 0.00 |
| 09 | 2 | 0.0% | -236 | -81.21 | -1.02 | 0.00 |
| 10 | 2 | 50.0% | -80 | 26.20 | 0.20 | 1.58 |
| 07 | 2 | 0.0% | -313 | -93.22 | -1.02 | 0.00 |
| 12 | 2 | 0.0% | -331 | -80.43 | -0.96 | 0.00 |
| 08 | 1 | 100.0% | 162 | 64.72 | 1.37 | n/a |
| 14 | 1 | 0.0% | -32 | -31.70 | -1.06 | 0.00 |
| 16 | 1 | 0.0% | -109 | -43.60 | -1.02 | 0.00 |
| 20 | 1 | 0.0% | -74 | -52.08 | -1.05 | 0.00 |
| 22 | 1 | 0.0% | -51 | -50.70 | -1.06 | 0.00 |
| 18 | 1 | 0.0% | -412 | -41.24 | -1.49 | 0.00 |

### Strategy version

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| rule-failed_breakout-0f3a97a6 | 15 | 26.7% | -1,119 | -221.83 | -0.33 | 0.54 |
| rule-trend_pullback-acf3f57d | 11 | 9.1% | -1,106 | -331.82 | -0.76 | 0.16 |
| rule-breakout-8d54bf35 | 6 | 33.3% | 38 | 18.08 | 0.11 | 1.13 |

## Exits

- stop_loss: 20 trades, avg -1.06R, median hold 4,002 s, net -2,445 pips
- take_profit: 7 trades, avg 1.63R, median hold 5,005 s, net 963 pips
- expiry: 5 trades, avg -0.59R, median hold 28,800 s, net -705 pips
- Stop-loss exits lost 1.06x the planned risk on average
- MFE/MAE: {'recorded_trades': 32, 'losers_that_reached_+0.5R': 9, 'losers_that_reached_+1R': 3, 'avg_winner_mfe_r': 1.655316222661959, 'avg_winner_realized_r': 1.6273267988447357, 'avg_mae_r': -0.8510430460587841}

## Costs

- Spread 39.23, slippage 49.00, commission 0.00, swap -0.87; average cost 0.072R per trade
- Median stop distance 107.7 pips (initial stop from context)

## Spacing

- Median gap after an exit 1,799 s; re-entries within 60 s: 9; within 5 min of a loss: 6

## Integrity

- Clean: False; issues: {'overlapping_positions': [['538ccbe13f5949fdbfa66443d00c72de', '3d3a238d6b3d48ce957a6f97b8719a27'], ['d53e486cc88644a2aa557219695b2abf', 'b73ec723e2ca475c89ca792c97387d5c'], ['89172136edef47d3aa28b7dc7f18cd98', '9cec09bedf9948c3b167726651b17d41'], ['9cec09bedf9948c3b167726651b17d41', 'b013ddfc69ac40839937e6f20783d5f7'], ['b013ddfc69ac40839937e6f20783d5f7', '15a370ef26bd4a9183d5d15822fea821'], ['9d4d5f51ebaf4d98915e00dd86b55e50', 'c3bb4ec671ea4478951f770c65b5a740'], ['48cb10f5e5c2409485c6850f4bab092b', 'e9b028651d694c9e856f67b9d21f769b'], ['6111018bf1714f638dedd999edf05f7c', '75ff1ef2add34dd1b40bb78e33049775'], ['75ff1ef2add34dd1b40bb78e33049775', '6f76f439529340fbbba7141e44f6952a']]}
- Implied money per price unit per lot: {'XAUUSD.sd': {'min': 99.99999999999999, 'max': 100.00000000000001}}

