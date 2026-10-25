# Blockers (need the owner)

| Item | Needed | Impact |
|------|--------|--------|
| MT5 terminals | Equiti demo is connected (MT5_2). MT5_1 is on MetaQuotes-Demo. Still needed: Exness and MultiBank demo logins (a third terminal folder for the third broker) | Read-only path verified on MetaQuotes-Demo and Equiti demo; Exness and MultiBank still unverified |
| Historical gold ticks | Real XAUUSD tick exports from each broker (MT5 Symbols → Ticks → Export, or the GoldAIBridge EA) | No real backtest or walk-forward result exists yet; all engine runs so far used synthetic test data |
| News data provider | Done for now: MT5 economic calendar via GoldAICalendar.mq5 (MT5_1). A licensed API is optional | Headlines are not interpreted (no provider) |
| Institutional data | Licensed COMEX futures / depth / COT data source | Institutional agent reports `available=false` until configured |
| Telegram / WhatsApp / push credentials | Owner to put Telegram bot token + chat id in config.local.json (asked 2026-10-22); WhatsApp Business Cloud API token + phone id; push endpoint | Channels tested with mocked HTTP only |
| Phone access to the VPS | Done: Tailscale on VPS and phone, `tailscale serve --bg 8001` (owner ran it 2026-10-22) | App reaches the dashboard; not yet tested beyond that |
| Packages, copy trading, oil signals, profit lock, community links | Owner decision (and a payment provider / broker programme where relevant) | Not built; the UI shows only the app's own data |
| Account size and risk tolerance | Owner to state them | Live risk settings are not proposed; all risk values are illustrative and real trading stays disabled |
| Licensed headline feed / X API | Owner decision on provider and budget (docs/AGENTIC_REDESIGN.md §2) | Stage 3 uses free official sources and the MT5 calendar only |
