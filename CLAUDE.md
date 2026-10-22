# CLAUDE.md — GOLD AI ADAPTIVE AGENTIC SCALPER

Read this first in every session, then PROJECT_STATUS.md, TASK_QUEUE.json and RESUME_INSTRUCTIONS.md.

## Non-negotiable rules
- Real-money execution stays DISABLED. Never set `real_trading_enabled` true, never create an owner grant,
  never call a broker `order_send` outside tests with fake MT5 modules. The master prompt is not live-trading permission.
- Never fabricate market data, backtest results, performance or progress. Synthetic data (`gold_ai.brokers.mock_feed`)
  is for tests only and is always labeled `synthetic`.
- Keep the four memory domains physically separate (tables `mem_a_..` to `mem_d_..`). Memory D accepts only actual fills.
- No martingale, grid, recovery sizing or risk escalation anywhere.
- Decisions on tick t fill on tick t+1. Learning happens only after a trade closes.
- Don't delete learning history; archival is explicit and owner-controlled.

## Layout
- `gold_ai/domain.py` core types · `config.py` settings · `costs.py` spread/commission/swap/slippage
- `gold_ai/brokers/` symbol discovery, read-only MT5 connector, synthetic feed + FakeMT5
- `gold_ai/market/` candles (M1..D1 + M10), features/regimes (Market Intelligence Agent), tick ingestion/validation
- `gold_ai/agents/` decision (adaptive model + calibration), institutional, maturity, self_healing, health
- `gold_ai/engines/` simulator, loop, backtest (A), walkforward (B), live_virtual (C), metrics
- `gold_ai/risk/engine.py` independent risk veto · `gold_ai/security/auth.py` auth, roles, owner grant, approvals
- `gold_ai/memory/store.py` persistence · `gold_ai/news/` · `gold_ai/notifications/` · `gold_ai/execution.py` gated MT5 execution
- `gold_ai/api/app.py` FastAPI · `gold_ai/runtime.py` wiring · `gold_ai/cli.py` CLI
- `dashboard/` React + TypeScript · `mql5/` read-only EA bridge · `deploy/` Windows scripts

## Commands
- Tests: `python -m pytest -q`
- Dashboard: `cd dashboard && npm ci && npx tsc --noEmit && npm run build`
- Run API: `python -m gold_ai --config config.local.json serve` (add `--mt5` on Windows with a logged-in terminal)

## Checkpoint protocol
After each milestone: run tests, update TASK_QUEUE.json, PROJECT_STATUS.md, COMPLETED_TASKS.md, TEST_RESULTS.md,
NEXT_ACTIONS.md, BLOCKERS.md; commit.
