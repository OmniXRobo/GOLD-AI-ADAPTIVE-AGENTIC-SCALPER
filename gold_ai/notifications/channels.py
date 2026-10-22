"""Notification channels. All HTTP goes through an injectable httpx.Client.

Secrets (bot tokens, access tokens) are never logged and never included in
error messages: ChannelError carries only the channel name and HTTP status.
Buttons carry a short callback reference ("ap|<signal>|<handle>"), not the
approval token itself, because Telegram limits callback_data to 64 bytes; the
SignalService resolves the reference to the server-held token.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Protocol

import httpx

from .signals import Signal

ACTION_CODES = {"approve": "ap", "reject": "rj", "ignore": "ig", "manual": "mn"}
CODE_ACTIONS = {v: k for k, v in ACTION_CODES.items()}


class _RedactSecrets(logging.Filter):
    """httpx logs request URLs at INFO; the Telegram bot token is part of that URL."""

    def __init__(self):
        super().__init__()
        self.secrets: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if any(s in msg for s in self.secrets):
            for s in self.secrets:
                msg = msg.replace(s, "***")
            record.msg, record.args = msg, ()
        return True


_redactor = _RedactSecrets()
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_redactor)


def register_secret(secret: str | None) -> None:
    if secret:
        _redactor.secrets.add(secret)


class ChannelError(Exception):
    """Delivery failure. The message must never contain a secret."""


@dataclass
class Outgoing:
    signal: Signal
    text: str
    callback_ref: str                 # "<signal_id>|<token handle>"
    approval_token: str | None = None  # only for trusted in-process channels (dashboard)

    def callback(self, action: str) -> str:
        return f"{ACTION_CODES[action]}|{self.callback_ref}"


class Channel(Protocol):
    name: str

    def send(self, msg: Outgoing) -> dict: ...


def _post(client: httpx.Client, name: str, url: str, **kw) -> httpx.Response:
    try:
        resp = client.post(url, **kw)
    except httpx.HTTPError as e:
        raise ChannelError(f"{name}: transport error {type(e).__name__}") from None
    if resp.status_code >= 400:
        raise ChannelError(f"{name}: HTTP {resp.status_code}")
    return resp


@dataclass
class TelegramChannel:
    """Telegram Bot API sendMessage with an inline keyboard."""

    bot_token: str
    chat_id: str
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=10.0))
    api_base: str = "https://api.telegram.org"
    name: str = "telegram"

    def __post_init__(self):
        register_secret(self.bot_token)

    def send(self, msg: Outgoing) -> dict:
        keyboard = [[{"text": "Approve", "callback_data": msg.callback("approve")},
                     {"text": "Reject", "callback_data": msg.callback("reject")}],
                    [{"text": "Ignore", "callback_data": msg.callback("ignore")},
                     {"text": "Took manually", "callback_data": msg.callback("manual")}]]
        resp = _post(self.client, self.name, f"{self.api_base}/bot{self.bot_token}/sendMessage",
                     json={"chat_id": self.chat_id, "text": msg.text,
                           "reply_markup": {"inline_keyboard": keyboard}})
        body = resp.json()
        if not body.get("ok"):
            raise ChannelError(f"{self.name}: API returned ok=false")
        return {"message_id": (body.get("result") or {}).get("message_id")}


@dataclass
class WhatsAppChannel:
    """Official WhatsApp Business Cloud API (graph.facebook.com/{version}/{phone_id}/messages).

    Interactive reply buttons only work inside the 24h customer-service window; outside
    it Meta requires a pre-approved template (set template_name to send one instead).
    """

    access_token: str
    phone_number_id: str
    recipient: str
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=10.0))
    api_version: str = "v20.0"
    template_name: str | None = None
    template_lang: str = "en"
    name: str = "whatsapp"

    def __post_init__(self):
        register_secret(self.access_token)

    def send(self, msg: Outgoing) -> dict:
        if self.template_name:
            payload = {"messaging_product": "whatsapp", "to": self.recipient, "type": "template",
                       "template": {"name": self.template_name, "language": {"code": self.template_lang},
                                    "components": [{"type": "body",
                                                    "parameters": [{"type": "text", "text": msg.text[:1000]}]}]}}
        else:
            buttons = [{"type": "reply", "reply": {"id": msg.callback(a), "title": t}}
                       for a, t in (("approve", "Approve"), ("reject", "Reject"), ("ignore", "Ignore"))]
            payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": self.recipient,
                       "type": "interactive",
                       "interactive": {"type": "button", "body": {"text": msg.text[:1024]},
                                       "action": {"buttons": buttons}}}
        resp = _post(self.client, self.name,
                     f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages",
                     json=payload, headers={"Authorization": f"Bearer {self.access_token}"})
        msgs = resp.json().get("messages") or [{}]
        return {"message_id": msgs[0].get("id")}


@dataclass
class PushChannel:
    """Generic web-push / FCM-style webhook. Pass `sender` to use your own push SDK instead of HTTP."""

    webhook_url: str | None = None
    sender: Callable[[dict], object] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    client: httpx.Client | None = None
    name: str = "push"

    def send(self, msg: Outgoing) -> dict:
        s = msg.signal
        payload = {"title": f"SIGNAL ONLY: {s.side} {s.symbol} @ {s.entry:.2f}", "body": msg.text,
                   "data": {"signal_id": s.id, "callback_ref": msg.callback_ref,
                            "actions": {a: msg.callback(a) for a in ACTION_CODES}}}
        if self.sender is not None:
            try:
                self.sender(payload)
            except Exception as e:
                raise ChannelError(f"{self.name}: sender error {type(e).__name__}") from None
            return {}
        if not self.webhook_url:
            raise ChannelError(f"{self.name}: no webhook_url or sender configured")
        client = self.client or httpx.Client(timeout=10.0)
        _post(client, self.name, self.webhook_url, json=payload, headers=self.headers)
        return {}


@dataclass
class DashboardChannel:
    """In-memory queue read by the authenticated dashboard API."""

    maxlen: int = 200
    name: str = "dashboard"
    queue: deque = field(default_factory=deque)

    def send(self, msg: Outgoing) -> dict:
        self.queue.append({"signal": msg.signal.to_dict(), "text": msg.text,
                           "approval_token": msg.approval_token})
        while len(self.queue) > self.maxlen:
            self.queue.popleft()
        return {}

    def drain(self) -> list[dict]:
        items = list(self.queue)
        self.queue.clear()
        return items

    def peek(self) -> list[dict]:
        return list(self.queue)


def channels_from_settings(settings, client: httpx.Client | None = None,
                           dashboard: DashboardChannel | None = None) -> list:
    """Dashboard always; Telegram / WhatsApp / push only when their settings are present."""
    client = client or httpx.Client(timeout=10.0)
    out: list = [dashboard or DashboardChannel()]
    if settings.telegram_bot_token and settings.telegram_chat_id:
        out.append(TelegramChannel(settings.telegram_bot_token, settings.telegram_chat_id, client))
    if settings.whatsapp_token and settings.whatsapp_phone_id and settings.whatsapp_recipient:
        out.append(WhatsAppChannel(settings.whatsapp_token, settings.whatsapp_phone_id, settings.whatsapp_recipient,
                                   client))
    if url := getattr(settings, "push_webhook_url", None):
        out.append(PushChannel(webhook_url=url, client=client))
    return out
