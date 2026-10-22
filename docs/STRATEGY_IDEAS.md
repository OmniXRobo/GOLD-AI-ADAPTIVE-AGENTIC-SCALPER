# Strategy ideas from a reference app (GOLDX), and how they could fit

The owner shared screenshots of GOLDX, a commercial XAUUSD signal app, as design and strategy inspiration.
This note lists what the screens show, what is actually verifiable from them, and how each idea could fit
this project's rules (real data only, learning after close, independent risk veto, no martingale/grid).
Nothing here is copied code; GOLDX's internals are not visible, so "technique" below means what the UI implies.

## What the screens show

| GOLDX feature | What it implies | Verifiable? |
|---|---|---|
| Signal card: side, entry *range* (e.g. 4124–4140), one SL, two TPs (TP1, TP2) | Layered/limit entries and partial take-profit | Levels yes; performance no |
| "Technical" tab: gauge from RSI, MACD, MA trend, 50/200 MA, Stochastic, Bollinger, buy/sell pressure, per timeframe | Multi-indicator sentiment vote | Method yes (standard indicators) |
| "Fundamental" tab: per-pair bias, market regime (DXY, oil, US 10Y/2Y, real yield), Fed watch with FedWatch hike odds, central bank quotes, breaking headlines | Macro bias layer from licensed news/market data | Needs data sources |
| "Calendar" tab: actual / forecast / previous with beat/miss | Economic calendar | Yes |
| "Autopilot": AI bot with risk per signal %, max drawdown per session, max profit per session, daily loss cap %, daily profit cap %; "copy trading" leaderboards | Per-session and per-day caps; social copy trading | Settings yes; claimed returns (+43 %, 88 % win rate, "100 % hands-free") are **not** verifiable |
| "Practice": demo balance, lot stepper, buy/sell against live chart, win/loss counter | Paper trading for users | Yes |
| Packages, broker affiliate links, coupons | Monetisation | Not relevant here |

## Fit with this project

1. **Multi-indicator technical sentiment** — done as a *display* (`/api/analysis/technical`, Analysis → Technical),
   computed from the engine's own candles. As a *model input* it is a candidate feature set (RSI14, MACD histogram,
   Stochastic %K, price vs MA50, MA50 vs MA200 on M15/H1). It must go in as a new model schema version, be
   trained only on closed trades, and be kept only if backtest **and** walk-forward on real Equiti ticks beat the
   current model after costs. Indicators are lagging; on a scalper they are more likely useful as a regime filter
   than as entry triggers.
2. **Fundamental bias** — partly done: Analysis → Fundamental shows the US data surprise bias, event risk and Fed
   events from the real MT5 calendar feed. Hike odds, yields, DXY and oil need a licensed market-data source
   (see BLOCKERS.md). As a model input this fits T-NEWS-FEATURES (`NewsAgent.regime_flags`).
3. **Entry range and TP1/TP2** — candidate engine change: place the entry as a limit zone (fill only if price
   trades into it on a later tick, which preserves the t → t+1 rule) and close half at TP1, move SL to break-even,
   run the rest to TP2. Must be modelled in the simulator with real spread/slippage first; it changes fill rates,
   so compare walk-forward results, not backtest alone. Never add size to a losing position (no averaging down).
4. **Session and daily caps** — our risk engine already has a daily loss cap and max drawdown. A daily *profit*
   cap and per-session caps are simple risk-engine additions and only ever reduce trading.
5. **Practice mode** — done (Practice tab), kept in the browser, separate from the four AI memories.
6. **Copy trading / leaderboards / packages** — out of scope; they need real multi-user track records and
   brokerage arrangements. Our dashboard shows only recorded results per memory domain.

## Suggested order (engine side, owner to approve)
1. Daily profit cap and per-session caps in the risk engine (small, safe).
2. Technical indicator features behind a new model version, validated by walk-forward on real ticks.
3. Entry zone + TP1/TP2 in the simulator, then compare walk-forward.
4. Macro inputs once a licensed data source is chosen.
