# Next actions

U. (VPS thread) After the profit-alerts PR is merged: `git pull`, rebuild the dashboard (`cd dashboard && npm ci &&
   npm run build`), restart GoldAI-Equiti, then build Android 1.5.0 with the existing signing key
   (docs/ANDROID_APP.md) and put `gold-ai-1.5.0.apk` in the project files. The bell appears in the dashboard
   header at once; the phone needs 1.5.0 for background profit notifications.

T. (VPS thread) After the research-lanes PR is merged: `git pull`, restart GoldAI-Equiti. Three research lanes start on
   XAUUSD.sd (failed_breakout, trend_pullback, breakout at intraday scale; simulation only, `style=research`, no
   signals). Check `/api/overview` → `research_lanes`. Weekly: `audit-trades --domain virtual --style research`.
   Also: backfill further back (`backfill-ticks ... --days 120`, check disk first) and rerun the round 3 command.

S. (VPS thread) After the round-3 PR is merged: `git pull`, restart GoldAI-Equiti (virtual engines stop taking
   momentum trades), then run the round 3 command in docs/research/README.md and share the report as-is.
   (the earlier audit and round 2 reports are committed in docs/audit and docs/research).

R. (VPS thread, first) After the root-cause-audit PR is merged: `git pull`, restart GoldAI-Equiti, then run
   `python -m gold_ai --config config.local.json audit-trades --domain virtual` and
   `... audit-trades --domain virtual --symbol XAUUSD --style scalp`; share both reports from `data/audit/` as-is,
   plus whether `news_calendar_files` is set in config.local.json and whether the Equiti account charges commission.
   Note: demo execution and signals of the adaptive strategy are now refused while it is under investigation.

0. (VPS thread) After the streaming-research PR is merged: `git pull`, check free disk (roughly 1 GB per 10 M ticks in
   SQLite), then `backfill-ticks --terminal-path "C:\Program Files\MT5_2" --symbol XAUUSD.sd --days 30` (it extends
   history backwards from the earliest stored tick) and re-run `research` with the round 2 grid in
   docs/research/README.md; share the report as-is.
A. (Done 2026-10-25) After the agentic-redesign PR is merged: `git pull`, `pip install -r requirements.txt` (adds tzdata),
   restart GoldAI-Equiti. Note that risk engine v2 now also limits the virtual engines (20 trades/day, cooldowns,
   no re-entry 5 min after a loss), so fewer virtual trades is expected. Then run
   `python -m gold_ai --config config.local.json research --broker equiti --symbol XAUUSD.sd` on the stored ticks
   and commit the report from `data/research/` as-is (task T-STAGE1-REAL-RESEARCH).
B. (Owner) Give account size and risk tolerance before any live risk settings are proposed (T-LIVE-RISK-SETTINGS).
C. (Dev) Stage 2 per docs/AGENTIC_REDESIGN.md §7: planner from research champions, TP1-3, signal lifecycle.

00. (VPS thread) After the trade-styles PR is merged: `git pull`, `npm ci && npm run build` in `dashboard/`, restart
   GoldAI-Equiti (keep `--symbol XAUUSD.sd`), check the log for `seeded ... broker bars` and `:swing` engines, then
   confirm BTCUSD swing shows ready on the weekend. Build Android 1.4.0 with the existing key.

0. (VPS thread) After the multi-instrument PR is merged: `git pull`, `npm ci && npm run build` in `dashboard/`, restart
   the GoldAI-Equiti task, check the log for `EURUSD -> EURUSD.sd` lines and disk use; build Android 1.3.0 with the
   existing key. New instruments warm up for ~100 minutes of quotes before they can signal.

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
    copy trading/rewards, oil signals, profit lock to breakeven, community links (TASK_QUEUE.json, T-PACKAGES etc.).
