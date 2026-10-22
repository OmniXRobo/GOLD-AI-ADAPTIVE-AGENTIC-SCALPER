# Completed tasks

## Session 1 — 2026-10-22
All items below have code + passing tests unless noted.
- P1 Foundation: repo, config (real trading off by default), domain types, SQLAlchemy store (SQLite/PostgreSQL),
  auth (scrypt, HMAC tokens, roles), audit log, checkpoint files.
- P2 Broker connectivity: metadata-validated gold symbol discovery; read-only MT5 connector (no order API);
  broker identification (Exness/Equiti/MultiBank/generic); account real/demo detection; tick collector with
  resume cursor; MT5 tick-export and CSV import with data-quality validation; read-only MQL5 bridge EA (not compiled).
- P3 Simulation: Bid/Ask simulator (spread, commission, swap incl. triple Wednesday, adverse slippage, stop gap
  fills, trailing, expiry); Engine A backtest (reproducible, data hash, Memory A); Engine B walk-forward (rolling/
  anchored, train/validate/test, degradation/overfit/stability flags, Memory B); Engine C live virtual (restart
  resume of model, equity, open positions, learning start; Memory C).
- P4 Adaptive intelligence: multi-timeframe candles M1–D1 + derived M10; causal features and regime detection;
  online-learning decision agent with calibrated confidence, WAIT by default without evidence; model registry.
- P5 Advanced: news calendar adapters/classifier/blackout; optional institutional agent (neutral when no data);
  self-healing detect → diagnose → bounded candidates → backtest → walk-forward → registry "validated";
  owner-only promote/rollback.
- P6 Notifications: signal-only mode (Telegram, WhatsApp Cloud API, push webhook, dashboard), signed single-use
  expiring approvals; approval never places orders.
- P7 Dashboard: React/TS, 24 pages, simulated/actual badges, emergency stop, owner authorization page;
  browser smoke-tested.
- P8 Controlled execution: gated MT5 execution adapter (demo/real modes, grant + allowlist + config + risk +
  broker checks), reconciliation, emergency close, trailing modify — tested with fake MT5 only; NOT wired into the
  running service.
- P9 partial: maturity engine, health agent + supervisor, backups with checksum manifest, Windows scripts and docs.

## Session 2 — 2026-10-22 (owner's Windows VPS)
- Installed on Windows Server 2022 (Python 3.12.10); full test suite passes on Windows.
- Read-only MT5 path verified on a real terminal (MetaQuotes-Demo, generic broker): connect, demo detection,
  XAUUSD discovery and spec, tick collection, live virtual engine start. Exness/Equiti/MultiBank still unverified.
- Fixed broker server time handling: the connector measures the server's UTC offset from live ticks (only from a
  tick that just changed, re-measured after market pauses) and returns true UTC; collector waits until it is known.
- Fixed `install.ps1` (hard-coded `py -3.11`) and `start.ps1` (passed `@args` instead of its arguments; stderr
  redirection stopped the script on PowerShell 5.1). Logs now go to `logs\gold_ai_<timestamp>.log`.
- Compiled GoldAIBridge.mq5 (0 errors, 1 warning).
