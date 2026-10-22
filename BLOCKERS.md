# Blockers (need the owner)

| Item | Needed | Impact |
|------|--------|--------|
| MT5 terminals | VPS is ready with two MT5 terminals; MT5_1 is logged in to MetaQuotes-Demo only. Log terminals in to Exness, Equiti and MultiBank demo accounts (one terminal per account) | Read-only path verified on MetaQuotes-Demo (generic broker) only; Exness/Equiti/MultiBank adapters still unverified on real servers |
| Historical gold ticks | Real XAUUSD tick exports from each broker (MT5 Symbols → Ticks → Export, or the GoldAIBridge EA) | No real backtest or walk-forward result exists yet; all engine runs so far used synthetic test data |
| News data provider | Choice of economic-calendar source (licensed API or exported CSV) | News blackout works from supplied events; no live calendar feed configured |
| Institutional data | Licensed COMEX futures / depth / COT data source | Institutional agent reports `available=false` until configured |
| Telegram / WhatsApp / push credentials | Bot token + chat id; WhatsApp Business Cloud API token + phone id; push endpoint | Channels tested with mocked HTTP only |
