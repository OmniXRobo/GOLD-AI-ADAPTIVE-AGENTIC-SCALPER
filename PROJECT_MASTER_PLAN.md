# Project master plan

Source of requirements: GOLD_AI_MASTER_REQUIREMENTS (project files) and the master development prompt.
Phases (status tracked in TASK_QUEUE.json):

1. Foundation — repo, architecture, database, configuration, authentication, checkpoints
2. Broker connectivity — MT5 connector, broker adapters, symbol discovery, read-only data, tick storage
3. Trading simulation — backtest, walk-forward, live virtual, cost models
4. Adaptive intelligence — market intelligence, features, decision models, continuous memory, model registry
5. Advanced intelligence — institutional flow, news, regimes, self-healing
6. Notifications — Telegram, WhatsApp, push, signal-only mode, owner approval workflow
7. Dashboard — frontend, real-time APIs, statistics, maturity, model comparison
8. Controlled execution — MT5 execution adapter, risk engine, owner authorization, demo tests, reconciliation
9. Production hardening — security review, performance, integration/failure tests, backups, monitoring, packaging
10. Acceptance — verify requirements, engines, persistence, broker compatibility (needs real broker terminals), controls

Definition of done: code exists, integrated, tests pass, error handling, logs, docs, security reviewed, status recorded.
A simulation is not a verified profitable strategy; a broker adapter is not verified until tested on that broker.
