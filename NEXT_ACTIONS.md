# Next actions

1. (Owner) Equiti demo is connected. Log terminals in to Exness and MultiBank demo accounts (one terminal per account; a third
   terminal folder is needed for the third broker), then start one `start.ps1` per terminal on different ports
   (task T-VERIFY-BROKERS).
2. (Owner) Create the owner account on the VPS: `.\.venv\Scripts\python.exe -m gold_ai --config config.local.json create-user owner`.
3. (Owner) Export real XAUUSD tick history per broker and import it; run the first real backtest and walk-forward
   (task T-REAL-DATA-RESEARCH). Report results as-is. The MetaQuotes-Demo ticks being collected now can also be
   used once enough history has accumulated.
4. (Dev) T-SUPERVISOR-WIRE: run collector/virtual/news workers under `agents.health.Supervisor` instead of bare threads.
5. (Dev) T-VIRTUAL-WARMUP-SEED: seed the virtual engine's market state from stored ticks after a restart.
6. (Dev) T-SELFHEAL-SCHEDULE: schedule self-healing cycles on Memory C trades (daily) and expose current diagnosis.
7. (Dev) T-NEWS-FEATURES: feed `NewsAgent.regime_flags` and institutional features into the decision model
   (requires model schema version bump + migration of stored model state).
8. (Dev) T-MULTI-TERMINAL: one process managing several terminals/brokers with separate memories per broker.
9. (Dev) T-TELEGRAM-WEBHOOK: inbound Telegram/WhatsApp callback endpoints calling `SignalService.handle_callback`.
10. (Dev) T-DASH-SPLIT: code-split the dashboard bundle.
11. (Dev) T-TORCH-MODEL: optional PyTorch candidate model class behind the same ModelState interface.
