# Next actions

1. (Owner) Provide a Windows VPS with demo MT5 terminals for Exness, Equiti and MultiBank, then run
   `deploy\windows\install.ps1` and `start.ps1`; record per-broker results in TEST_RESULTS.md (task T-VERIFY-BROKERS).
2. (Owner) Export real XAUUSD tick history per broker and import it; run the first real backtest and walk-forward
   (task T-REAL-DATA-RESEARCH). Report results as-is.
3. (Dev) T-SUPERVISOR-WIRE: run collector/virtual/news workers under `agents.health.Supervisor` instead of bare threads.
4. (Dev) T-SELFHEAL-SCHEDULE: schedule self-healing cycles on Memory C trades (daily) and expose current diagnosis.
5. (Dev) T-NEWS-FEATURES: feed `NewsAgent.regime_flags` and institutional features into the decision model
   (requires model schema version bump + migration of stored model state).
6. (Dev) T-MULTI-TERMINAL: one process managing several terminals/brokers with separate memories per broker.
7. (Dev) T-TELEGRAM-WEBHOOK: inbound Telegram/WhatsApp callback endpoints calling `SignalService.handle_callback`.
8. (Dev) T-DASH-SPLIT: code-split the dashboard bundle.
9. (Dev) T-TORCH-MODEL: optional PyTorch candidate model class behind the same ModelState interface.
