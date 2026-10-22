# Resume instructions

1. Read CLAUDE.md, PROJECT_STATUS.md, TASK_QUEUE.json, TEST_RESULTS.md, BLOCKERS.md.
2. `git status` and `git log --oneline -15` — confirm the working tree is clean and matches the last checkpoint.
   Repo: https://github.com/OmniXRobo/GOLD-AI-ADAPTIVE-AGENTIC-SCALPER (branch `main`).
   Fallback: git bundle in the project files folder (`gold-ai-scalper/gold-ai-scalper.bundle`).
3. `pip install -r requirements.txt` then `python -m pytest -q` — must match TEST_RESULTS.md before new work.
4. Take the first task in TASK_QUEUE.json with status `todo` (lowest `priority` number first). Tasks marked
   `blocked` need something from the owner (see BLOCKERS.md); skip them.
5. Work, test, then update all checkpoint files and commit.

Automatic resume after a usage-limit reset is not possible from inside the code. The owner can schedule a
recurring Claude Code session (cloud routine or local scheduler) whose prompt is:
"Continue GOLD AI from RESUME_INSTRUCTIONS.md; keep real-money execution disabled." That is owner-configured,
respects platform limits and does not bypass them.
