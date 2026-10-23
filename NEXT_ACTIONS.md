# Next actions

1. (Owner, later) Equiti only for now. When ready, log terminals in to Exness and MultiBank demo accounts (one terminal per account; a third
   terminal folder is needed for the third broker), then start one `start.ps1` per terminal on different ports
   (task T-VERIFY-BROKERS).
2. (Owner) Create the owner account on the VPS: `.\.venv\Scripts\python.exe -m gold_ai --config config.local.json create-user owner`.
3. (Owner) Export real XAUUSD tick history per broker and import it; run the first real backtest and walk-forward
   (task T-REAL-DATA-RESEARCH). Report results as-is. The MetaQuotes-Demo ticks being collected now can also be
   used once enough history has accumulated.
4. (Dev) T-NEWS-FEATURES: feed `NewsAgent.regime_flags` and institutional features into the decision model
   (requires model schema version bump + migration of stored model state).
5. (Dev) T-MULTI-TERMINAL: one process managing several terminals/brokers with separate memories per broker.
6. (Dev) T-TELEGRAM-WEBHOOK: inbound Telegram/WhatsApp callback endpoints calling `SignalService.handle_callback`.
8. (Dev) T-TORCH-MODEL: optional PyTorch candidate model class behind the same ModelState interface.
9. (Owner) Phone access: install Tailscale on the VPS and the phone, run `tailscale serve --bg 8001` on the VPS,
   install the APK and sign in (docs/ANDROID_APP.md, task T-ANDROID-DEVICE-TEST).
10. (Owner) Decide on the reference-site features that need outside services or engine work: paid packages/coupons,
    copy trading/rewards, forex/oil/crypto signals, profit lock to breakeven, community links (TASK_QUEUE.json, T-PACKAGES etc.).
- (Owner, optional) Quiver API token in config.local.json, then check `/api/altdata` (docs/ALT_DATA.md).
