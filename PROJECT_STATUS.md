# Project status — 2026-10-22 (session 2, owner's Windows VPS)

**Real-money execution: DISABLED. Demo execution: DISABLED.** No order has been sent to any broker.
No real-market performance exists yet.

## Session 2 (VPS)
- Installed on the VPS at `C:\Users\Administrator\Desktop\GOLD-AI-ADAPTIVE-AGENTIC-SCALPER` (Python 3.12.10, venv).
  Tests 159 passed / 1 skipped.
- Running read-only against the MT5 terminal logged in to **MetaQuotes-Demo** (not one of the three target brokers):
  real XAUUSD demo ticks are being collected; the live virtual engine is warming up. See TEST_RESULTS.md.
- Fixed: broker server time → UTC conversion in the MT5 connector (ticks were 3 h off); Windows install/start scripts.
- MQL5 bridge compiled (0 errors).
- Still needed from the owner: Exness / Equiti / MultiBank demo logins, tick exports, and an owner account
  (`create-user owner` asks for a password, so the owner runs it). See BLOCKERS.md.


## State
- Code for every component in the master plan exists with automated tests: 159 passed / 1 skipped
  (156/156 with PostgreSQL). See TEST_RESULTS.md.
- Verified only against simulated/fake brokers (FakeMT5) and synthetic data. Nothing has been verified on
  Exness, Equiti or MultiBank yet — that requires the owner's Windows VPS (BLOCKERS.md).
- Execution adapter exists and is tested with a fake MT5 module; it is intentionally not wired into the service.

## Where the code lives
- GitHub: https://github.com/OmniXRobo/GOLD-AI-ADAPTIVE-AGENTIC-SCALPER (branch `main`, public).
- Backup copy: git bundle in the project files folder `gold-ai-scalper/gold-ai-scalper.bundle`.

## Next task
First `todo` in TASK_QUEUE.json: **T-SUPERVISOR-WIRE** (then T-VIRTUAL-WARMUP-SEED). Owner-blocked tasks with priority 1:
T-VERIFY-BROKERS and T-REAL-DATA-RESEARCH.
