# Decisions

| # | Date | Decision | Why |
|---|------|----------|-----|
| 1 | 2026-10-22 | Python core + FastAPI + SQLAlchemy; React/TS dashboard; MQL5 EA only as read-only bridge | MT5's official Python API gives ticks/specs/orders without running strategy logic in MQL5; keeps one code path for simulation and live |
| 2 | 2026-10-22 | Four physically separate trade tables | Spec requires independent memories; prevents accidental mixing in queries |
| 3 | 2026-10-22 | Online logistic model per side + reliability calibrator (no PyTorch yet) | Small-sample regime: needs to learn from tens of trades, be inspectable and serializable; PyTorch can be added as a candidate model class later |
| 4 | 2026-10-22 | Exploration only in simulation, flagged `[EXPLORATION]` in explanation and context | Model needs outcomes to learn; real/signal decisions must only come from validated evidence, otherwise WAIT |
| 5 | 2026-10-22 | Fill on next tick after decision | Removes same-tick look-ahead |
| 6 | 2026-10-22 | Real execution needs config flag + owner grant (password + phrase, expiry, account + lot scope) + allowlist + no emergency stop | Defence in depth; no single setting enables real money |
| 7 | 2026-10-22 | SQLite default, PostgreSQL supported via URL | Runs immediately on a Windows VPS; PostgreSQL recommended for production |
| 8 | 2026-10-22 | No GitHub repo attached in this session: work kept in a local git repo and exported as a git bundle to the project files folder | Persist work between sessions without an attached remote |
