"""Authentication, role-based permissions, owner authorization and approval tokens.

Real-money execution needs ALL of:
  1. settings.real_trading_enabled = True (config, set by the owner on the VPS),
  2. an unexpired owner grant created with the owner's password and an exact
     confirmation phrase, scoped to specific allowlisted accounts and a lot cap,
  3. the target account present in settings.account_allowlist,
  4. no active emergency stop.
Nothing in development or tests ever satisfies (1).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from enum import Enum

from ..config import Settings
from ..memory.store import MemoryStore

CONFIRM_PHRASE = "I AUTHORIZE REAL MONEY TRADING"


class Permission(str, Enum):
    OBSERVE = "observe"
    BACKTEST = "backtest"
    FORWARD_VALIDATION = "forward_validation"
    VIRTUAL_TRADING = "virtual_trading"
    SIGNALS = "signals"
    DEMO_EXECUTION = "demo_execution"
    REAL_EXECUTION = "real_execution"
    ADMIN = "admin"


ROLES: dict[str, set[Permission]] = {
    "viewer": {Permission.OBSERVE},
    "operator": {Permission.OBSERVE, Permission.BACKTEST, Permission.FORWARD_VALIDATION,
                 Permission.VIRTUAL_TRADING, Permission.SIGNALS},
    # Owner role holds every permission, but REAL_EXECUTION still needs an active grant.
    "owner": set(Permission),
}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
    except ValueError:
        return False
    salt = base64.b64decode(s)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(base64.b64encode(dk).decode(), h)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class TokenSigner:
    def __init__(self, secret: str):
        if not secret or len(secret) < 16:
            raise ValueError("secret_key must be at least 16 characters")
        self.key = secret.encode()

    def sign(self, payload: dict, ttl_seconds: int) -> str:
        body = dict(payload, exp=int(time.time()) + ttl_seconds, nonce=secrets.token_hex(8))
        raw = _b64(json.dumps(body, sort_keys=True).encode())
        sig = _b64(hmac.new(self.key, raw.encode(), hashlib.sha256).digest())
        return f"{raw}.{sig}"

    def verify(self, token: str) -> dict | None:
        try:
            raw, sig = token.split(".")
        except ValueError:
            return None
        good = _b64(hmac.new(self.key, raw.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(good, sig):
            return None
        body = json.loads(_unb64(raw))
        if body.get("exp", 0) < time.time():
            return None
        return body


@dataclass
class User:
    username: str
    role: str

    def has(self, perm: Permission) -> bool:
        return perm in ROLES.get(self.role, set())


class AuthService:
    def __init__(self, settings: Settings, store: MemoryStore):
        self.settings = settings
        self.store = store
        self.signer = TokenSigner(settings.secret_key)

    # -- users --------------------------------------------------------------------
    def create_user(self, username: str, password: str, role: str, actor: str = "system") -> None:
        if role not in ROLES:
            raise ValueError(f"unknown role {role}")
        if len(password) < 10:
            raise ValueError("password must be at least 10 characters")
        users = self.store.kv_get("users", {}) or {}
        if username in users:
            raise ValueError("user exists")
        users[username] = {"hash": hash_password(password), "role": role}
        self.store.kv_set("users", users)
        self.store.audit(actor, "user_created", {"username": username, "role": role})

    def authenticate(self, username: str, password: str) -> User | None:
        u = (self.store.kv_get("users", {}) or {}).get(username)
        ok = bool(u) and verify_password(password, u["hash"])
        self.store.audit(username, "login_success" if ok else "login_failed", {})
        return User(username, u["role"]) if ok else None

    SESSION_TTL = 8 * 3600
    # "Keep me signed in" (always on in the Android app): the token lasts 30 days and the dashboard renews it
    # on every start, so a user who opens the app at least once a month stays signed in until they sign out.
    REMEMBER_TTL = 30 * 24 * 3600

    def issue_token(self, user: User, ttl_seconds: int | None = None, remember: bool = False) -> str:
        ttl = ttl_seconds or (self.REMEMBER_TTL if remember else self.SESSION_TTL)
        return self.signer.sign({"sub": user.username, "role": user.role, "typ": "session", "rem": remember}, ttl)

    def refresh_token(self, token: str) -> tuple[str, User] | None:
        """A fresh session token with the same lifetime for a valid one; the user's current role is used."""
        body = self.signer.verify(token)
        u = self.user_from_token(token)
        if not body or u is None:
            return None
        return self.issue_token(u, remember=bool(body.get("rem"))), u

    # -- read-only device tokens (Android app signal alerts) ------------------------
    # A device token only lets a phone read the signal list in the background; it is
    # never accepted where a session token is required. Bumping the epoch revokes all.
    DEVICE_TOKEN_TTL = 30 * 24 * 3600

    def issue_device_token(self, user: User, device: str = "") -> str:
        epoch = int(self.store.kv_get("device_token_epoch", 0) or 0)
        self.store.audit(user.username, "device_token_issued", {"device": device[:64]})
        return self.signer.sign({"sub": user.username, "role": user.role, "typ": "device", "epoch": epoch,
                                 "device": device[:64]}, self.DEVICE_TOKEN_TTL)

    def user_from_device_token(self, token: str) -> User | None:
        body = self.signer.verify(token)
        if not body or body.get("typ") != "device":
            return None
        if body.get("epoch") != int(self.store.kv_get("device_token_epoch", 0) or 0):
            return None
        u = (self.store.kv_get("users", {}) or {}).get(body["sub"])
        return User(body["sub"], u["role"]) if u else None

    def revoke_device_tokens(self, actor: User) -> None:
        epoch = int(self.store.kv_get("device_token_epoch", 0) or 0)
        self.store.kv_set("device_token_epoch", epoch + 1)
        self.store.audit(actor.username, "device_tokens_revoked", {})

    def user_from_token(self, token: str) -> User | None:
        body = self.signer.verify(token)
        if not body or body.get("typ") != "session":
            return None
        users = self.store.kv_get("users", {}) or {}
        u = users.get(body["sub"])
        return User(body["sub"], u["role"]) if u else None

    # -- owner real-execution grant ------------------------------------------------
    def grant_real_execution(self, owner: User, password: str, phrase: str, accounts: list[str],
                             max_lots: float, hours: float) -> dict:
        if owner.role != "owner":
            raise PermissionError("only the owner can authorize real execution")
        if self.authenticate(owner.username, password) is None:
            raise PermissionError("password re-confirmation failed")
        if phrase != CONFIRM_PHRASE:
            raise PermissionError("confirmation phrase mismatch")
        if not accounts:
            raise ValueError("grant must name at least one account")
        not_allowed = [a for a in accounts if a not in self.settings.account_allowlist]
        if not_allowed:
            raise PermissionError(f"accounts not in configured allowlist: {not_allowed}")
        if not 0 < hours <= 24 * 7:
            raise ValueError("grant duration must be within (0, 168] hours")
        grant = {"accounts": accounts, "max_lots": max_lots, "expires": time.time() + hours * 3600,
                 "granted_by": owner.username, "granted_at": time.time()}
        self.store.kv_set("real_execution_grant", grant)
        self.store.audit(owner.username, "real_execution_granted", grant)
        return grant

    def revoke_real_execution(self, actor: str, reason: str = "") -> None:
        self.store.kv_set("real_execution_grant", None)
        self.store.audit(actor, "real_execution_revoked", {"reason": reason})

    def real_execution_allowed(self, account: str, account_is_real: bool, lots: float) -> tuple[bool, str]:
        if self.store.kv_get("emergency_stop", False):
            return False, "emergency stop active"
        if not account_is_real:
            return False, "account is not a real account (use demo execution path)"
        if not self.settings.real_trading_enabled:
            return False, "real trading disabled in configuration"
        if account not in self.settings.account_allowlist:
            return False, "account not in allowlist"
        g = self.store.kv_get("real_execution_grant")
        if not g:
            return False, "no owner authorization grant"
        if g["expires"] < time.time():
            return False, "owner authorization expired"
        if account not in g["accounts"]:
            return False, "account not covered by owner grant"
        if lots > g["max_lots"]:
            return False, f"lots {lots} exceed granted maximum {g['max_lots']}"
        return True, "authorized"

    def demo_execution_allowed(self, account_is_real: bool) -> tuple[bool, str]:
        if self.store.kv_get("emergency_stop", False):
            return False, "emergency stop active"
        if account_is_real:
            return False, "demo execution path refuses real accounts"
        if not self.settings.demo_execution_enabled:
            return False, "demo execution disabled in configuration"
        return True, "demo authorized"

    # -- emergency stop -----------------------------------------------------------
    def set_emergency_stop(self, actor: str, active: bool, reason: str = "") -> None:
        self.store.kv_set("emergency_stop", active)
        self.store.audit(actor, "emergency_stop" if active else "emergency_stop_cleared", {"reason": reason})

    # -- signal approval tokens ---------------------------------------------------
    def issue_approval(self, signal_id: str, ttl_seconds: int = 60) -> str:
        return self.signer.sign({"typ": "approval", "signal": signal_id}, ttl_seconds)

    def consume_approval(self, token: str, signal_id: str) -> bool:
        body = self.signer.verify(token)
        if not body or body.get("typ") != "approval" or body.get("signal") != signal_id:
            return False
        used = self.store.kv_get("used_approvals", []) or []
        if body["nonce"] in used:
            return False
        used.append(body["nonce"])
        self.store.kv_set("used_approvals", used[-5000:])
        self.store.audit("approval", "signal_approved", {"signal": signal_id})
        return True
