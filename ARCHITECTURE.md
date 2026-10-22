# Architecture

```
 MT5 terminal(s) ──(MetaTrader5 py, read-only)──► MT5ReadOnlyConnector ──► TickCollector ──► ticks table
        │                                              │
        └─ GoldAIBridge.mq5 (CSV ticks + spec JSON) ─► import-ticks / import-spec
                                                       ▼
                                            MarketIntelligenceAgent (M1..D1, M10, features, regime)
 News sources ─► NewsAgent ──────┐                     │
 Licensed futures/COT ─► Institutional (optional) ─────┤
                                                       ▼
                                            TradingDecisionAgent (online logistic per side + calibrator)
                                                       │ proposal (BUY/SELL/WAIT, SL/TP/trail, lots, cost, conf)
                                                       ▼
                                            RiskEngine (independent veto; sizing from equity & stop only)
                                                       │
        ┌──────────────────────────────┬───────────────┴───────────┬───────────────────────────────┐
        ▼                              ▼                           ▼                               ▼
 Engine A backtest           Engine B walk-forward        Engine C live virtual          Execution adapter
 (PositionSimulator)         train | validate | test      (live quotes, est. fills)      (demo/real; owner grant +
 Memory A                    Memory B                     Memory C                        config + allowlist) Memory D
        └──────────────► Maturity engine ◄──── Self-healing (detect → candidates → A → B → registry "validated")
                                   │                                  promotion to "approved" = owner only
                                   ▼
                     FastAPI (/api, /ws/live) ──► React dashboard / mobile / Signal channels (Telegram, WhatsApp, push)
```

## Key properties
- Execution and risk never wait on a cloud LLM; news interpretation is asynchronous and optional.
- One shared `TradingLoop` drives all engines so simulated behaviour is identical across A/B/C.
- Fills: BUY at Ask / exit at Bid; SELL at Bid / exit at Ask; adverse slippage; stops fill at the worse of
  stop and market; same-tick ambiguity resolves to the stop. Orders fill on the tick after the decision.
- Confidence = calibrated observed hit-rate for the model's probability bucket (Beta prior), not raw model output.
- Storage: SQLAlchemy; SQLite for development, PostgreSQL (`postgresql+psycopg://...`) for production.
  For large tick volumes on PostgreSQL, convert `ticks` to a TimescaleDB hypertable (see docs/INSTALL_WINDOWS.md).
