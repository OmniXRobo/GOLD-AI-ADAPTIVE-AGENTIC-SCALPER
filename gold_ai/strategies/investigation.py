"""Strategy investigations: strategies under a root-cause investigation can't be promoted, executed or signalled.

A flag targets an exact strategy version or a whole strategy family. The adaptive agent's versions
(`strat-...`) and the self-healing variations derived from it (`heal-...`) form one family, so flagging
the family also blocks perturbed copies of the same candidate generators. Flags are kept in the store
(kv `strategy_investigations`) and every change goes to the audit log. Nothing about the strategy's
trades, model or history is changed or deleted: virtual (simulation) trading carries on and keeps
collecting evidence. Only the owner can close an investigation.
"""
from __future__ import annotations

from datetime import datetime, timezone

KEY = "strategy_investigations"
ADAPTIVE_FAMILY = "family:adaptive-v1"

# Opened by the root-cause audit of the losing live-virtual results (docs/ROOT_CAUSE_AUDIT.md).
INITIAL_INVESTIGATIONS: dict[str, str] = {
    ADAPTIVE_FAMILY: (
        "Root-cause audit 2026-10-26: live-virtual results lost (owner screenshot: 34 trades, 32.4% win rate, "
        "PF ~0.50). Every trade so far was an exploration trade of the momentum / rejection candidate rules, "
        "which showed no edge in real-data research either. Blocked from promotion, execution and signals "
        "until the investigation is closed by the owner. See docs/ROOT_CAUSE_AUDIT.md."),
}


def family_of(strategy_version: str | None) -> str | None:
    v = strategy_version or ""
    if v.startswith(("strat-", "heal-")):
        return ADAPTIVE_FAMILY
    if v.startswith("rule-"):
        return "family:rule-" + v[5:].rsplit("-", 1)[0]
    return None


def _all(store) -> dict[str, dict]:
    return dict(store.kv_get(KEY, {}) or {})


def seed(store, actor: str = "root_cause_audit") -> list[str]:
    """Open the initial investigations once. One the owner has closed is not reopened. Returns the keys opened."""
    flags, opened = _all(store), []
    for target, reason in INITIAL_INVESTIGATIONS.items():
        if target not in flags:
            flags[target] = {"status": "open", "reason": reason, "opened_at": _now(), "opened_by": actor}
            opened.append(target)
    if opened:
        store.kv_set(KEY, flags)
        for t in opened:
            store.audit(actor, "investigation_opened", {"target": t, "reason": flags[t]["reason"]})
    return opened


def open_investigation(store, target: str, reason: str, actor: str) -> dict:
    flags = _all(store)
    entry = {"status": "open", "reason": reason, "opened_at": _now(), "opened_by": actor,
             "previous": flags.get(target)}
    flags[target] = entry
    store.kv_set(KEY, flags)
    store.audit(actor, "investigation_opened", {"target": target, "reason": reason})
    return entry


def close_investigation(store, target: str, owner_user, reason: str) -> dict:
    if getattr(owner_user, "role", None) != "owner":
        raise PermissionError("only the owner can close a strategy investigation")
    if not reason.strip():
        raise ValueError("closing an investigation needs a reason")
    flags = _all(store)
    cur = flags.get(target)
    if cur is None or cur.get("status") != "open":
        raise KeyError(f"no open investigation for {target}")
    flags[target] = {**cur, "status": "closed", "closed_at": _now(), "closed_by": owner_user.username,
                     "close_reason": reason}
    store.kv_set(KEY, flags)
    store.audit(owner_user.username, "investigation_closed", {"target": target, "reason": reason})
    return flags[target]


def blocking(store, strategy_version: str | None) -> dict | None:
    """The open investigation that blocks this strategy version (exact or family), or None."""
    flags = _all(store)
    for target in (strategy_version, family_of(strategy_version)):
        f = flags.get(target) if target else None
        if f and f.get("status") == "open":
            return {"target": target, **f}
    return None


def listing(store) -> list[dict]:
    return [{"target": k, **v} for k, v in _all(store).items()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
