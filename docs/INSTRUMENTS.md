# Instruments: gold, Bitcoin and major forex pairs

The live service analyses these instruments, each with its own AI model, virtual account and learning history.
Everything is **signal-only and virtual**: real-money and demo execution stay disabled.

| Instrument | Pip | Max spread | Slippage (per side, adverse) | Trading hours (UTC) | News that blacks it out |
|---|---|---|---|---|---|
| XAUUSD | $0.10 | global `risk.max_spread_points` | global `costs` | global `risk.allowed_sessions_utc` | every currency (as before) |
| BTCUSD | $1 | 60 pips ($60) | 5 pips | 24 h, 7 days | USD |
| EURUSD | 0.0001 | 2.0 pips | 0.2 pips | 06:00–20:45 | EUR, USD |
| GBPUSD | 0.0001 | 2.5 pips | 0.2 pips | 06:00–20:45 | GBP, USD |
| USDCHF | 0.0001 | 2.5 pips | 0.2 pips | 06:00–20:45 | USD, CHF |
| USDJPY | 0.01 | 2.0 pips | 0.2 pips | 00:00–20:45, 22:15–24:00 | USD, JPY |
| AUDUSD | 0.0001 | 2.0 pips | 0.2 pips | 00:00–20:45, 22:15–24:00 | AUD, USD |
| NZDUSD | 0.0001 | 3.0 pips | 0.2 pips | 00:00–20:45, 22:15–24:00 | NZD, USD |
| USDCAD | 0.0001 | 2.5 pips | 0.2 pips | 11:00–20:45 | USD, CAD |

Forex hours skip the 20:45–22:15 UTC rollover, when spreads widen. Stops get an extra 0.5 pip (forex) or 10 pips
(BTC) of adverse slippage. Bitcoin has no triple-swap Wednesday; it is charged every night. These are starting
limits, not tuned values.

Contract size, tick value (P/L in the account currency, which handles JPY and CHF quotes), digits, swaps, volume
limits and stop levels always come from the broker's own symbol metadata, never from this table.

## How symbols are matched
For each instrument the service looks for the broker's symbol (`EURUSD`, `EURUSD.sd`, `EURUSDm` ...) and accepts it
only when the broker's base and profit currencies match (Bitcoin CFDs that report a USD base are accepted when the
description says Bitcoin). When several match, the one with the same suffix as the gold symbol wins, so on Equiti
`XAUUSD.sd` leads to `EURUSD.sd`, `BTCUSD.sd` and so on. An instrument the broker does not offer is logged and
skipped. Check the service log for lines like `EURUSD -> EURUSD.sd (equiti)`.

## Choosing instruments
- Default: all nine. Config: `"symbols": ["XAUUSD", "BTCUSD", "EURUSD"]` in `config.local.json`.
- Command line: `serve --mt5 --symbols XAUUSD,BTCUSD,EURUSD` (or `start.ps1 -Symbols XAUUSD,BTCUSD`).
- `--symbol XAUUSD.sd` still pins the gold symbol (or any other instrument's broker symbol).
- Change a limit per instrument: `"instrument_overrides": {"BTCUSD": {"max_spread_pips": 40},
  "EURUSD": {"sessions_utc": [[7, 17]]}}`.

## Separate memories
Each instrument's live virtual engine stores its model, equity, open positions and learning start under
`virtual:<broker>:<symbol>:*`, so one market never learns from another. Its trades go to Memory C with their own
symbol, and the Results, Signals, Home and Analysis pages filter by instrument. Self-healing runs per instrument.
Ticks are collected per symbol and warm-up replays each symbol's own stored ticks, so new instruments start
"warming up" until they have about 20 M5 bars (roughly 100 minutes of quotes).

## Load on the VPS
Nine symbols means nine collectors and nine engines polling the terminal. Tick storage grows with the number of
symbols (forex majors and BTC are busy). Watch disk use in System → Health; reduce `symbols` if needed.

## Backtests for other instruments
`backfill-ticks --instrument EURUSD --days 5` copies the broker's tick history for that instrument, then
`backtest --broker equiti --symbol EURUSD.sd`. The spec is stored by `serve --mt5` the first time it sees the symbol.
