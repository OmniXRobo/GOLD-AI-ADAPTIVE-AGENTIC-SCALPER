# Blockers (need the owner)

| Item | Needed | Impact |
|------|--------|--------|
| MT5 terminals | Windows VPS with Exness / Equiti / MultiBank MT5 terminals logged in (demo accounts first) | Broker adapters, symbol discovery and live virtual trading are only verified against FakeMT5; not yet against real brokers |
| Historical gold ticks | Real XAUUSD tick exports from each broker (MT5 Symbols → Ticks → Export, or the GoldAIBridge EA) | No real backtest or walk-forward result exists yet; all engine runs so far used synthetic test data |
| News data provider | Choice of economic-calendar source (licensed API or exported CSV) | News blackout works from supplied events; no live calendar feed configured |
| Institutional data | Licensed COMEX futures / depth / COT data source | Institutional agent reports `available=false` until configured |
| Telegram / WhatsApp / push credentials | Bot token + chat id; WhatsApp Business Cloud API token + phone id; push endpoint | Channels tested with mocked HTTP only |
| GitHub repository | Connect GitHub / create a repo for this project | Work is stored as a git bundle in project files; no remote yet |
| MQL5 compile | MetaEditor on the VPS | GoldAIBridge.mq5 has not been compiled |
