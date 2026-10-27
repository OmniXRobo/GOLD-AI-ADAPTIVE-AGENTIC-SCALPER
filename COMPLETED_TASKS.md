# Completed tasks

## Session 5 — 2026-10-27 (profit alerts)
- `gold_ai/notifications/trade_alerts.py`: alerts for trades that closed with a positive net result, read from
  Memory C (virtual) and Memory D (real); each says virtual or real and whether it was an exploration trade.
- API: `GET /api/alerts/profit-closes` (session) and `GET /api/device/profit-closes` (phone device token).
- Dashboard: header bell with unread count, list of recent profitable closes, pop-up for each new one, optional
  browser notifications. Android 1.5.0 source: "Trades closed in profit" notification channel.

## Session 4d — 2026-10-27 (strategy selector)
- gold_ai/agents/strategy_selector.py: joins each research lane's latest research verdict (Memory A) with its
  forward virtual trades (Memory C); owner-configurable `promotion_criteria` (default: research `candidate`,
  ≥30 forward trades, forward expectancy ≥ +0.05R with 90% interval above zero, drawdown ≤ 10R).
  Owner-only promotion of an eligible lane to champion (its proposals stop being exploration and may become
  signals, virtual fills only); automatic demotion after 20 trades below −0.15R; all audited.
- API: GET /api/strategies/scoreboard, POST /api/strategies/promote, POST /api/strategies/demote.

## Session 4c — 2026-10-26 (forward research lanes)
- Round 3 report committed (all insufficient_data; failed_breakout positive on validation and test, beat baseline).
- `ResearchLaneEngine` (gold_ai/engines/research_lanes.py): research setups traded virtually on live quotes,
  simulation only, no learning, no signals, `style=research`, own account, positions survive restarts.
  Configured by `research_lanes` / `research_lane_symbols` (default: 3 intraday setups on XAUUSD).

## Session 4b — 2026-10-26 (towards a new strategy)
- Live-virtual engines: momentum continuation off by default (`virtual_entry_rules`); promoted strategies cannot
  re-enable it; engine status lists its entry rules.
- Research: `tf_scale: intraday` runs every setup a timeframe slower; `intraday-round3` variant preset; matched
  baselines follow the scale.

## Session 4 — 2026-10-26 (root-cause audit)
- docs/ROOT_CAUSE_AUDIT.md: 24-item audit, confirmed defects vs hypotheses H1–H6.
- Strategy investigations (gold_ai/strategies/investigation.py): adaptive family blocked from promotion,
  rollback, execution and signals; owner-only close, audited; registry snapshot of each engine's model.
- Decision agent: expectancy from realized payoff per direction (`Payoff`), backward-compatible model schema.
- Simulator: initial stop, MFE/MAE, trailing flag stored on each closed trade.
- `/api/trades`: exploration vs model-approved metrics; per-trade exploration/investigation fields.
- `audit-trades` CLI (gold_ai/research/trade_audit.py): dashboard-identical headline, breakdowns, R statistics,
  exits, costs, spacing, integrity checks.

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
- Owner decision: Equiti demo only for now (MetaQuotes-Demo service stopped).
- T-SUPERVISOR-WIRE: background workers run under `Supervisor` (restart with backoff, incidents audited).
- T-VIRTUAL-WARMUP-SEED: `LiveVirtualEngine.warm_up` rebuilds market state from stored ticks after a restart.
- Dashboard built on the VPS (Node 22) and served by the running service; `register-task.ps1` gained `-Port`.
- Auto-start: scheduled task `GoldAI-Equiti` (logon, restart on failure) runs the Equiti service.
- T-SELFHEAL-SCHEDULE: daily self-healing check on Memory C, current diagnosis exposed to the dashboard.
- Session tokens redacted from uvicorn logs.

## Session 2b — 2026-10-22 (dashboard UI and Android app, cloud)
- T-DASH-REDESIGN: dark gold theme (light/auto selectable), icon navigation, slimmer real-trading banner with a
  compact STOP button on phones, live XAUUSD price ticker (real ticks only, hidden when no engine runs), Overview hero
  card, better stat tiles and bottom tabs (Overview, Market, Signals, Virtual, More).
- T-DASH-SPLIT: pages load on demand and charts are a separate chunk; first load ~83 kB gzip (was ~203 kB).
- T-ANDROID-APP: `android/` native app (API 24+): dashboard WebView with server setup, connection error screen and
  read-only signal notifications. Built with `android/build.sh`; APK signature verified. Not yet run on a phone.
- Backend: read-only device tokens (`POST /api/auth/device-token`, `GET /api/device/signals`,
  `POST /api/auth/device-token/revoke-all`), 30-day TTL, revocable, audited.
- Fixed: `POST /api/signals/{id}/action` read its JSON body as a query parameter, so dashboard Approve/Reject always
  failed with 422. Fixed: the static dashboard route could resolve paths outside the build folder.

## Session 2c — 2026-10-22 (simplified UI inspired by a reference app, cloud)
- T-UI-SIMPLE: cream/gold light theme is the default (dark still selectable). Main navigation is Home, Autopilot,
  Analysis, Practice, Signals; every earlier page is kept under "Advanced" (Overview moved to /overview).
- Home: live price card, latest signal cards (entry, SL, TP), Memory C results only once trades have closed.
- Analysis: Technical (new `/api/analysis/technical`), Fundamental (US data surprise bias, event risk, Fed events
  from the real calendar; yields/odds marked as not connected), Calendar (actual/forecast/previous).
- Practice: browser-only paper trading on the live price, separate from all AI memories.
- Fixed: Signals table read `time`/`lots`/`explanation`, but the backend sends `timestamp`/`suggested_lots`/`reason`.
- Android app 1.1.0 (cream colours), same signing key as 1.0.0. docs/STRATEGY_IDEAS.md records the reference
  app's techniques and how they could fit, as owner-approved follow-up tasks.

## Session 2d — 2026-10-23
- Results page (win rate, pips, money by period; last 50 closed trades), Learn page (calculator, money guide, how it
  works, FAQ), public landing page, nav updates. Android app 1.2.0.
- Session 2e: Results period filters/tiles/history cards, Home next-event card, Autopilot performance card, app 1.2.1.

## Session 2f — 2026-10-23
- T-MULTI-ASSET-SIGNALS: BTCUSD + 7 forex majors alongside gold. `gold_ai/instruments.py` (pip, limits, sessions,
  news currencies, triple-swap day, symbol matching), metadata-validated discovery preferring the gold symbol's
  suffix, per-instrument engines/collectors/self-healing in the runtime, `settings.symbols` / `--symbols`,
  `instrument_overrides`, `/api/instruments`, `symbol` filters on trades/market/technical, signal text with
  per-instrument decimals and SL/TP pips, server-time offset tracked per symbol (BTC streams through weekends).
  Dashboard market filters and Android 1.3.0 source. Tests: tests/test_instruments.py.

## Session 2g — 2026-10-24
- Scalping and swing signal styles per instrument (separate engines, memory, signals, self-healing); dashboard
  style chips and tags; Android 1.4.0 alert label; broker-bar warm-up; promoted versions applied to live engines.
- Fixes: websocket send-after-close crash, signal store race, state reads moving tick_accel, Signals Domain column.

## Session 3 — 2026-10-25 (agentic redesign)
- docs/AGENTIC_REDESIGN.md: gap analysis, architecture, data sources/costs, DB design, research plan, risk spec,
  degraded mode, staged plan with acceptance criteria.
- Stage 1: indicator library, strategy setup library, rule agent (simulation-only), research harness + CLI
  `research`, feature evaluation, EV after costs in the decision agent, risk engine v2, Dubai-time sessions,
  day-rollover fix. Tested on synthetic data only.
- 2026-10-25: first real-data research run committed (docs/research/); research streams ticks from the DB.
- 2026-10-27: fixed app pages hanging (websocket DB read off the event loop, no-cache index.html, non-overlapping
  polling with 30 s GET timeout, page Retry). APK 1.5.0 built and signed with the existing key.
- 2026-10-27: stay signed in (30-day remembered session renewed on start; always on in the Android app).
- 2026-10-27: Android 1.5.1 (no WebView state restore, cache cleared after an app update).
