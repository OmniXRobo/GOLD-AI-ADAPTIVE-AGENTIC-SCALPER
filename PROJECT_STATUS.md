# Project status — 2026-10-22 (session 2, owner's Windows VPS)

**Real-money execution: DISABLED. Demo execution: DISABLED.** No order has been sent to any broker.
No real-market performance exists yet.

## Session 2b (dashboard UI and Android app)
- Dashboard redesigned (dark gold theme, icons, live price from real ticks only, mobile layout) and code-split.
- Android app in `android/` (dashboard + read-only signal alerts). APK built and signature-verified; **not yet tested
  on a phone**. Phone access needs Tailscale on the VPS and phone (docs/ANDROID_APP.md).
- Fixed the signal Approve/Reject endpoint (was always rejected with 422). Tests 165 passed / 1 skipped.
- After merging, the VPS needs `git pull` and `npm run build` in `dashboard/` to serve the new UI.

## Session 2 (VPS)
- Installed on the VPS at `C:\Users\Administrator\Desktop\GOLD-AI-ADAPTIVE-AGENTIC-SCALPER` (Python 3.12.10, venv).
  Tests 159 passed / 1 skipped.
- **Owner decision (14:03 UTC): focus on Equiti only for now.** One read-only service runs: port 8001 on **Equiti demo**
  (MT5_2, XAUUSD.sd). The MetaQuotes-Demo service (port 8000) was stopped; its collected ticks stay in the DB:
  real XAUUSD demo ticks are being collected; the live virtual engine is warming up. See TEST_RESULTS.md.
- Fixed: broker server time → UTC conversion in the MT5 connector (ticks were 3 h off); Windows install/start scripts.
- Added: Supervisor-run workers (crash restart with backoff), virtual-engine warm-up from stored ticks, dashboard
  built and served by the service (Node 22 on the VPS). register-task.ps1 takes -Port. Auto-start task **GoldAI-Equiti** registered (owner OK) and running the service.
- Added: daily scheduled self-healing check on Equiti virtual trades; session tokens redacted from logs.
- MQL5 bridge compiled (0 errors).
- Still needed from the owner: Exness and MultiBank demo logins, tick exports, and an owner account
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
First `todo` in TASK_QUEUE.json: **T-NEWS-FEATURES**. Owner-blocked tasks with priority 1:
T-VERIFY-BROKERS and T-REAL-DATA-RESEARCH.
