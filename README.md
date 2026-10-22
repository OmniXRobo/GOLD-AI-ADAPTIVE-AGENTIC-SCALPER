# GOLD AI ADAPTIVE AGENTIC SCALPER

Adaptive multi-agent research, simulation and signal platform for XAUUSD on MetaTrader 5
(Exness, Equiti, MultiBank and other MT5 brokers). **Real-money trading is disabled by default** and requires
explicit, expiring owner authorization (docs/SECURITY.md).

- Three testing engines: historical backtest, walk-forward validation, live virtual forward trading.
- Four separate persistent memories: historical, forward validation, live virtual, real.
- Adaptive decision agent with calibrated confidence; independent risk engine; self-healing with owner-only promotion.
- Signal-only mode: Telegram, WhatsApp Business, push, dashboard.
- FastAPI + React dashboard (24 pages), mobile-ready API.
- Android app (`android/`, docs/ANDROID_APP.md): the dashboard on your phone plus read-only signal alerts.

Start here: CLAUDE.md · PROJECT_STATUS.md · ARCHITECTURE.md · docs/INSTALL_WINDOWS.md · docs/SECURITY.md

```bash
pip install -r requirements.txt
python -m pytest -q
python -m gold_ai create-user owner
python -m gold_ai serve            # research mode; add --mt5 on Windows with a logged-in terminal
```

No performance claims: a simulation is not a verified profitable strategy, and past results do not predict future ones.
