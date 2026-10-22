"""SignalService: create, deliver, persist and act on trade signals.

Approval NEVER places an order. `act(..., "approve")` only marks the signal
approved and returns execution_requested=True; any execution goes through the
separate, owner-gated execution path, which re-checks risk and authorization.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ..domain import Tick, TradeProposal, utcnow
from ..memory.store import MemoryStore
from ..security.auth import AuthService
from .channels import CODE_ACTIONS, Channel, ChannelError, Outgoing
from .signals import Signal, SignalStatus, format_signal

log = logging.getLogger(__name__)

SIGNALS_KEY = "signals"
TOKENS_KEY = "signal_approval_tokens"
ACTIONS = {"approve": SignalStatus.APPROVED, "reject": SignalStatus.REJECTED,
           "ignore": SignalStatus.IGNORED, "manual": SignalStatus.MANUAL}


@dataclass
class ActionResult:
    ok: bool
    reason: str
    signal: Signal | None = None
    execution_requested: bool = False


def _handle(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


class SignalService:
    def __init__(self, store: MemoryStore, auth: AuthService, channels: list[Channel] | None = None,
                 approval_ttl_seconds: int = 120, max_retries: int = 3, backoff_seconds: float = 0.5,
                 max_kept: int = 500, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], datetime] = utcnow):
        self.store, self.auth = store, auth
        self.channels = list(channels or [])
        self.approval_ttl_seconds = approval_ttl_seconds
        self.max_retries, self.backoff_seconds = max_retries, backoff_seconds
        self.max_kept = max_kept
        self.sleep, self.clock = sleep, clock

    # -- persistence -------------------------------------------------------------
    def _load(self) -> dict[str, dict]:
        return self.store.kv_get(SIGNALS_KEY, {}) or {}

    def _save(self, s: Signal) -> None:
        data = self._load()
        data[s.id] = s.to_dict()
        if len(data) > self.max_kept:
            for k in sorted(data, key=lambda k: data[k]["timestamp"])[: len(data) - self.max_kept]:
                data.pop(k)
        self.store.kv_set(SIGNALS_KEY, data)

    def get(self, signal_id: str) -> Signal | None:
        d = self._load().get(signal_id)
        return Signal.from_dict(d) if d else None

    def list(self, status: SignalStatus | str | None = None, limit: int = 100) -> list[Signal]:
        sigs = [Signal.from_dict(d) for d in self._load().values()]
        if status is not None:
            sigs = [s for s in sigs if s.status == SignalStatus(status)]
        return sorted(sigs, key=lambda s: s.timestamp, reverse=True)[:limit]

    def _tokens(self) -> dict[str, str]:
        return self.store.kv_get(TOKENS_KEY, {}) or {}

    def _set_token(self, signal_id: str, token: str | None) -> None:
        toks = self._tokens()
        if token is None:
            toks.pop(signal_id, None)
        else:
            toks[signal_id] = token
        self.store.kv_set(TOKENS_KEY, dict(list(toks.items())[-self.max_kept:]))

    # -- create & deliver ------------------------------------------------------------
    def create(self, proposal: TradeProposal, tick: Tick, broker: str, symbol: str = "XAUUSD") -> Signal:
        now = self.clock()
        s = Signal.from_proposal(proposal, tick, broker, symbol, now=now)
        ttl = max(1, min(self.approval_ttl_seconds, int((s.expiry - now).total_seconds()) + 1))
        token = self.auth.issue_approval(s.id, ttl_seconds=ttl)
        self._set_token(s.id, token)
        self._save(s)
        self.store.audit("signals", "signal_created", {"signal": s.id, "side": s.side, "broker": broker})
        self.deliver(s, token)
        return s

    def deliver(self, s: Signal, token: str) -> list[dict]:
        msg = Outgoing(s, format_signal(s), f"{s.id}|{_handle(token)}", approval_token=token)
        results = []
        for ch in self.channels:
            results.append(self._send_with_retry(ch, msg))
        s.deliveries.extend(results)
        self._save(s)
        return results

    def _send_with_retry(self, ch: Channel, msg: Outgoing) -> dict:
        name = getattr(ch, "name", type(ch).__name__)
        err = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                info = ch.send(msg) or {}
                return {"channel": name, "ok": True, "attempts": attempt, "error": "",
                        "time": self.clock().isoformat(), **{k: v for k, v in info.items() if k == "message_id"}}
            except ChannelError as e:
                err = str(e)
            except Exception as e:  # a broken channel must never block the others
                err = f"{name}: {type(e).__name__}"
            log.warning("signal %s delivery via %s failed (attempt %d): %s", msg.signal.id, name, attempt, err)
            if attempt < self.max_retries:
                self.sleep(self.backoff_seconds * 2 ** (attempt - 1))
        return {"channel": name, "ok": False, "attempts": self.max_retries, "error": err,
                "time": self.clock().isoformat()}

    # -- actions -------------------------------------------------------------------------
    def expire_stale(self) -> list[str]:
        now, out = self.clock(), []
        for s in self.list(SignalStatus.PENDING, limit=self.max_kept):
            if s.is_expired(now):
                s.status, s.acted_at = SignalStatus.EXPIRED, now
                self._save(s)
                self._set_token(s.id, None)
                out.append(s.id)
        return out

    def act(self, signal_id: str, action: str, token: str, actor: str = "user") -> ActionResult:
        if action not in ACTIONS:
            return ActionResult(False, f"unknown action {action!r}")
        s = self.get(signal_id)
        if s is None:
            return ActionResult(False, "unknown signal")
        now = self.clock()
        if s.status == SignalStatus.PENDING and s.is_expired(now):
            s.status, s.acted_at = SignalStatus.EXPIRED, now
            self._save(s)
            self._set_token(s.id, None)
            return ActionResult(False, "signal expired", s)
        if s.status != SignalStatus.PENDING:
            return ActionResult(False, f"signal already {s.status.value}", s)
        if action == "approve":
            valid = self.auth.consume_approval(token, signal_id)   # single-use nonce
        else:
            body = self.auth.signer.verify(token)
            valid = bool(body) and body.get("typ") == "approval" and body.get("signal") == signal_id
        if not valid:
            self.store.audit(actor, "signal_action_denied", {"signal": signal_id, "action": action})
            return ActionResult(False, "invalid or expired approval token", s)
        s.status, s.acted_by, s.acted_at = ACTIONS[action], actor, now
        self._save(s)
        self._set_token(s.id, None)
        self.store.audit(actor, f"signal_{s.status.value}", {"signal": signal_id, "order_placed": False})
        return ActionResult(True, s.status.value, s, execution_requested=(action == "approve"))

    def handle_callback(self, data: str, actor: str) -> ActionResult:
        """Resolve a Telegram callback_data / WhatsApp button id ("ap|<signal>|<handle>")."""
        try:
            code, signal_id, handle = data.split("|")
            action = CODE_ACTIONS[code]
        except (ValueError, KeyError):
            return ActionResult(False, "malformed callback")
        token = self._tokens().get(signal_id)
        if token is None:
            s = self.get(signal_id)
            if s is not None and s.status == SignalStatus.PENDING and s.is_expired(self.clock()):
                return self.act(signal_id, action, "", actor)
            return ActionResult(False, "no active approval for signal", s)
        if not hmac.compare_digest(_handle(token), handle):
            return ActionResult(False, "callback does not match signal")
        return self.act(signal_id, action, token, actor)
