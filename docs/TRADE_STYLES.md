# Trade styles: scalping and swing

Every instrument (XAUUSD, BTCUSD, the forex majors) runs two live virtual engines side by side. Both are
signal-only and virtual; neither can send an order.

| | Scalping (`scalp`) | Swing (`swing`) |
|---|---|---|
| Bars the features use (fast, base, slow) | M1, M5, M15 | M15, H1, H4 |
| Stop loss | 1.5 × M5 ATR + spread | 1.5 × H1 ATR + spread |
| Take profit | 1.5 R | 2.0 R |
| Trailing stop | starts at +1 R, trails 0.8 R | starts at +1.2 R, trails 1 R |
| Longest hold | 1 hour | 3 days (swap is charged) |
| Signal valid for | 60 s | 5 min |
| Closed trades per direction before real signals | 50 | 30 |
| Warm-up after a restart | 7 days of stored ticks | 2 days of stored ticks |

Shared by both: the same candidate setups (momentum continuation, rejection at support/resistance), the
calibrated-confidence floor (0.55), positive expectancy after costs, and the independent risk veto
(spread, session, news blackout, daily loss, drawdown, lot limits). Risk per trade is the same 0.5% of the
engine's virtual equity, so the wider swing stop means smaller lots, not more risk.

## Separate memory
- Each style has its own virtual account (starts at 10,000), open position, learning model and calibrator,
  stored under `virtual:<broker>:<symbol>` (scalping, the key used before styles existed, so its learning
  carries on) and `virtual:<broker>:<symbol>:swing`.
- Memory C trades carry `context.style`. Trades recorded before styles existed are scalping.
  `GET /api/trades/virtual?style=swing` filters; every trade row has a `style` field.
- Signals carry `style`, `style_label` and `max_hold_seconds`; alert text starts with `SCALPING` or `SWING`.
- Self-healing runs per engine (per symbol and style) and only compares trades of that style. A promoted
  version retires only the earlier approved version for the same symbol and style.
- `settings.trade_styles` (default `["scalp", "swing"]`) turns a style off for every instrument.

## Broker bars at warm-up
On start, each engine asks the terminal for its recent bars (`copy_rates_from_pos`, read-only) and keeps
those that closed before the first stored tick it replays. A symbol collected for only a few hours (BTCUSD
and the forex pairs were added on 2026-10-23) therefore has H1/H4/D1 history at once, and swing signals do
not have to wait 20 hours for hourly bars. If the terminal cannot provide bars, the engine falls back to
ticks only.

## Learning and new versions
- The model of each engine learns from every closed virtual trade (win or loss after costs). No expiry.
- Until it has enough closed trades per direction, about 1 setup in 5 is taken as a learning trade
  (`[EXPLORATION]`). Learning trades never become signals.
- Strategy settings (SL/TP multiples, thresholds, hold time) change only through self-healing: a check every
  24 h per engine, which needs at least 20 trades both before and in the last 50, acts only on a measured
  deterioration, and registers a variation as "validated" only if it beats the current one in a backtest and
  a walk-forward on the last 2 days of ticks. The owner promotes it; promotion now loads the new settings into
  the live engine (the learned model is kept) and survives restarts.
- Swing trades are fewer and longer, so the 2-day self-healing test window rarely has enough swing trades to
  validate anything yet. That is expected; it will not promote what it cannot test.
