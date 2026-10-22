# Security and owner authorization

## Permissions
Roles: `viewer` (observe), `operator` (observe, backtest, forward validation, virtual trading, signals),
`owner` (all). Permissions are separate for observation, backtesting, forward validation, virtual trading,
signals, demo execution and real-money execution.

## Real-money execution — all must hold
1. `real_trading_enabled: true` in the VPS config (default false).
2. Account login in `account_allowlist`.
3. An unexpired owner grant: owner password re-entry + exact phrase `I AUTHORIZE REAL MONEY TRADING`,
   scoped to listed accounts, a max lot size and a duration ≤ 7 days. Granting is audited.
4. The account is detected as REAL by MT5 (`ACCOUNT_TRADE_MODE_REAL`); demo accounts use the separate demo path.
5. No active emergency stop; the independent risk engine approves the trade with fresh market data.
A maturity score never enables trading. Signal approvals are signed, expiring, single-use tokens and never place
orders by themselves.

## Credentials
- Broker passwords are never stored by the app; the MT5 terminal holds the session.
- Passwords are hashed with scrypt; session tokens are HMAC-SHA256 signed with expiry.
- Put tokens (Telegram, WhatsApp) only in `config.local.json` or environment variables (`GOLDAI_*`);
  restrict the file to the service user (`icacls config.local.json /inheritance:r /grant:r "%USERNAME%:R"`).
- `/api/settings` masks secrets.

## Emergency stop
Dashboard banner button or `POST /api/emergency-stop`. Any operator can activate it; only the owner can clear it.
It closes virtual positions, blocks new trades in every engine and (when execution is configured) closes real ones.

## Audit
Logins, user creation, grants/revocations, emergency stops, model stage changes, backtests and imports are written
to the append-only `audit_log` table.
