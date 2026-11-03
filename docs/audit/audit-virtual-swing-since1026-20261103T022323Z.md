# Trade audit: virtual

Filters: {'broker': 'equiti', 'style': 'swing', 'since': '2026-10-26'}. Closed trades: 71.

Period: 2026-10-26T00:45:39.801000+00:00 to 2026-11-02T19:25:54.215000+00:00

## Headline (dashboard arithmetic)

- Trades 71: 27 wins / 44 losses, win rate 38.0%
- Pips: +3,739 / -6,781, net -3,042; PF (pips) 0.55
- Average win 138.5 pips, average loss 154.1 pips
- Money: net -583.11, PF (money) 0.50
- Trades whose pip sign and money sign differ: 1

## Outcomes in R

- Expectancy -0.27R, 90% CI (-0.47, -0.06)
- Average win 0.97R, average loss -1.03R
- Break-even win rate at this payoff 51.5%; observed 38.0%; P(win rate this low | break-even) = 0.016

### Exploration vs model-approved

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| exploration | 71 | 38.0% | -3,042 | -583.11 | -0.27 | 0.50 |

### Entry rule

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| rejection_support | 31 | 38.7% | 575 | -182.96 | -0.24 | 0.62 |
| rejection_resistance | 22 | 40.9% | -750 | -139.31 | -0.29 | 0.55 |
| momentum_continuation | 18 | 33.3% | -2,866 | -260.83 | -0.28 | 0.30 |

### Symbol

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| BTCUSD.lv | 12 | 33.3% | -2,081 | -238.21 | -0.43 | 0.38 |
| GBPUSD.sd | 10 | 30.0% | -73 | -73.53 | -0.41 | 0.49 |
| XAUUSD.sd | 10 | 30.0% | -811 | -195.67 | -0.45 | 0.33 |
| USDCHF.sd | 8 | 25.0% | -57 | -69.63 | -0.49 | 0.36 |
| EURUSD.sd | 8 | 50.0% | 6 | 6.12 | 0.11 | 1.09 |
| USDCAD.sd | 7 | 42.9% | -64 | -46.23 | -0.43 | 0.24 |
| USDJPY.sd | 6 | 50.0% | 10 | 7.82 | -0.12 | 1.16 |
| NZDUSD.sd | 5 | 60.0% | 20 | 20.31 | 0.20 | 1.89 |
| AUDUSD.sd | 5 | 40.0% | 7 | 5.91 | 0.07 | 1.19 |

### Style

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| swing | 71 | 38.0% | -3,042 | -583.11 | -0.27 | 0.50 |

### Side

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| BUY | 40 | 37.5% | -382 | -302.51 | -0.28 | 0.53 |
| SELL | 31 | 38.7% | -2,660 | -280.60 | -0.25 | 0.46 |

### Exit reason

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| stop_loss | 43 | 0.0% | -6,781 | -1,158.39 | -1.05 | 0.00 |
| trailing_stop | 18 | 100.0% | 1,159 | 181.63 | 0.49 | n/a |
| take_profit | 8 | 100.0% | 2,512 | 349.66 | 1.98 | n/a |
| expiry | 2 | 50.0% | 69 | 43.99 | 0.79 | 207.64 |

### Regime at entry

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| ranging | 58 | 39.7% | -3,698 | -538.76 | -0.24 | 0.45 |
| trending_down | 8 | 37.5% | 687 | -25.07 | -0.35 | 0.78 |
| trending_up | 5 | 20.0% | -30 | -19.27 | -0.46 | 0.72 |

### Entry hour (Dubai)

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| 10 | 8 | 62.5% | 31 | 34.36 | 0.34 | 1.67 |
| 17 | 8 | 12.5% | -1,159 | -182.04 | -0.76 | 0.01 |
| 05 | 5 | 60.0% | -151 | -36.62 | -0.12 | 0.45 |
| 19 | 5 | 40.0% | -527 | -80.21 | -0.44 | 0.22 |
| 13 | 4 | 25.0% | -207 | -56.38 | -0.65 | 0.15 |
| 14 | 4 | 50.0% | -628 | 28.18 | 0.36 | 1.44 |
| 15 | 4 | 25.0% | -273 | -73.44 | -0.68 | 0.06 |
| 00 | 4 | 50.0% | -633 | -26.54 | 0.05 | 0.65 |
| 04 | 3 | 66.7% | 5 | 1.05 | 0.00 | 1.08 |
| 16 | 3 | 66.7% | 20 | 18.73 | 0.49 | 1.95 |
| 11 | 3 | 0.0% | -39 | -41.77 | -1.08 | 0.00 |
| 18 | 3 | 33.3% | -43 | -31.79 | -0.61 | 0.28 |
| 06 | 2 | 50.0% | -537 | -23.45 | 0.47 | 0.54 |
| 22 | 2 | 50.0% | 602 | 48.51 | 0.44 | 4.69 |
| 23 | 2 | 50.0% | 1,677 | 74.99 | 0.49 | 5.01 |
| 20 | 2 | 0.0% | -273 | -77.45 | -1.03 | 0.00 |
| 21 | 2 | 0.0% | -41 | -38.97 | -1.05 | 0.00 |
| 03 | 2 | 0.0% | -331 | -48.62 | -1.07 | 0.00 |
| 08 | 2 | 50.0% | -215 | -39.10 | -0.34 | 0.11 |
| 12 | 1 | 0.0% | -10 | -10.41 | -1.10 | 0.00 |
| 01 | 1 | 0.0% | -588 | -49.98 | -1.04 | 0.00 |
| 07 | 1 | 100.0% | 279 | 27.85 | 0.67 | n/a |

### Strategy version

| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |
|---|---|---|---|---|---|---|
| strat-a290cf732c | 53 | 39.6% | -175 | -322.27 | -0.26 | 0.59 |
| strat-0c5bd67174 | 18 | 33.3% | -2,866 | -260.83 | -0.28 | 0.30 |

## Exits

- stop_loss: 43 trades, avg -1.05R, median hold 12,469 s, net -6,781 pips
- take_profit: 8 trades, avg 1.98R, median hold 60,160 s, net 2,512 pips
- trailing_stop: 18 trades, avg 0.49R, median hold 29,242 s, net 1,159 pips
- expiry: 2 trades, avg 0.79R, median hold 289,805 s, net 69 pips
- Stop-loss exits lost 1.05x the planned risk on average
- MFE/MAE: {'recorded_trades': 70, 'losers_that_reached_+0.5R': 13, 'losers_that_reached_+1R': 3, 'avg_winner_mfe_r': 1.6697152841249467, 'avg_winner_realized_r': 0.9721380952828391, 'avg_mae_r': -0.7387653664122489}

## Costs

- Spread 79.58, slippage 78.75, commission 0.00, swap -1.95; average cost 0.124R per trade
- Median stop distance 18.7 pips (some stops are the final (trailed) stop; the initial stop was not stored)

## Spacing

- Median gap after an exit 6,572 s; re-entries within 60 s: 1; within 5 min of a loss: 0

## Integrity

- Clean: True; issues: none
- Implied money per price unit per lot: {'NZDUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'BTCUSD.lv': {'min': 1.0, 'max': 1.0}, 'USDCHF.sd': {'min': 120748.15557192362, 'max': 121376.89954847796}, 'GBPUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'EURUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}, 'XAUUSD.sd': {'min': 99.99999999999999, 'max': 100.0}, 'USDCAD.sd': {'min': 71181.97672349362, 'max': 71533.8283474255}, 'USDJPY.sd': {'min': 632.9794977940664, 'max': 634.5821910853892}, 'AUDUSD.sd': {'min': 99999.99999999999, 'max': 100000.0}}

