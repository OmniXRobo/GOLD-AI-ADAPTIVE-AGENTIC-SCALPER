import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from gold_ai.config import Settings
from gold_ai.domain import Side, Tick, TradeProposal
from gold_ai.notifications import (ChannelError, DashboardChannel, PushChannel, Signal, SignalService, SignalStatus,
                                   TelegramChannel, WhatsAppChannel, channels_from_settings, format_signal)
from gold_ai.security.auth import AuthService

BOT_TOKEN = "123456:SECRET-BOT-TOKEN"
WA_TOKEN = "EAAG-SECRET-WA-TOKEN"


class Clock:
    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def __call__(self):
        return self.now


def proposal(now, valid=60):
    return TradeProposal(side=Side.BUY, entry=2400.20, stop_loss=2398.20, take_profit=2403.20, lots=0.05,
                         confidence=0.62, valid_until=now + timedelta(seconds=valid), expected_cost=4.1,
                         explanation="BUY: momentum continuation; regime=trend")


def tick(now):
    return Tick(now, 2400.00, 2400.20)


class Recorder:
    def __init__(self, fail_times=0, status=200, body=None):
        self.requests: list[httpx.Request] = []
        self.fail_times, self.status, self.body = fail_times, status, body

    def __call__(self, req):
        self.requests.append(req)
        if len(self.requests) <= self.fail_times:
            return httpx.Response(self.status)
        return httpx.Response(200, json=self.body if self.body is not None else {"ok": True})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def auth(settings, store):
    return AuthService(settings, store)


def make_service(store, auth, clock, channels):
    return SignalService(store, auth, channels, sleep=lambda s: None, clock=clock)


def test_signal_from_proposal_and_format(clock):
    now = clock()
    s = Signal.from_proposal(proposal(now), tick(now), "mock", now=now)
    assert (s.side, s.entry, s.stop_loss, s.take_profit) == ("BUY", 2400.20, 2398.20, 2403.20)
    assert s.risk_reward == pytest.approx(1.5) and s.suggested_lots == 0.05
    assert s.spread == pytest.approx(0.2) and s.estimated_costs == 4.1 and s.confidence == 0.62
    assert s.status == SignalStatus.PENDING and s.expiry == now + timedelta(seconds=60)
    assert Signal.from_dict(json.loads(json.dumps(s.to_dict()))) == s
    text = format_signal(s)
    assert text.startswith("SIGNAL ONLY — no order placed") and "does not execute" in text


def test_telegram_payload_and_short_callbacks(store, auth, clock):
    rec = Recorder(body={"ok": True, "result": {"message_id": 42}})
    svc = make_service(store, auth, clock, [TelegramChannel(BOT_TOKEN, "999", rec.client())])
    s = svc.create(proposal(clock()), tick(clock()), "mock")
    req = rec.requests[0]
    assert req.url.path == f"/bot{BOT_TOKEN}/sendMessage"
    body = json.loads(req.content)
    assert body["chat_id"] == "999" and "SIGNAL ONLY" in body["text"]
    buttons = [b for row in body["reply_markup"]["inline_keyboard"] for b in row]
    assert all(len(b["callback_data"].encode()) <= 64 for b in buttons)
    approve = next(b["callback_data"] for b in buttons if b["text"] == "Approve")
    assert approve.startswith(f"ap|{s.id}|")
    stored = svc.get(s.id)
    assert stored.deliveries[0] == {"channel": "telegram", "ok": True, "attempts": 1, "error": "",
                                    "time": stored.deliveries[0]["time"], "message_id": 42}
    res = svc.handle_callback(approve, actor="telegram:999")
    assert res.ok and res.execution_requested and res.signal.status == SignalStatus.APPROVED
    assert svc.handle_callback(approve, actor="telegram:999").ok is False   # single use


def test_whatsapp_cloud_api_payload(store, auth, clock):
    rec = Recorder(body={"messages": [{"id": "wamid.1"}]})
    ch = WhatsAppChannel(WA_TOKEN, "PHONEID", "971500000000", rec.client())
    svc = make_service(store, auth, clock, [ch])
    svc.create(proposal(clock()), tick(clock()), "mock")
    req = rec.requests[0]
    assert req.url.host == "graph.facebook.com" and req.url.path.endswith("/PHONEID/messages")
    assert req.headers["authorization"] == f"Bearer {WA_TOKEN}"
    body = json.loads(req.content)
    assert body["messaging_product"] == "whatsapp" and body["to"] == "971500000000"
    assert body["interactive"]["action"]["buttons"][0]["reply"]["id"].startswith("ap|")
    ch.template_name = "gold_signal"
    svc.create(proposal(clock()), tick(clock()), "mock")
    assert json.loads(rec.requests[1].content)["type"] == "template"


def test_retry_backoff_and_failing_channel_does_not_block_others(store, auth, clock, caplog):
    sleeps = []
    flaky = Recorder(fail_times=2, status=502)
    dead = Recorder(fail_times=99, status=401)
    dash = DashboardChannel()

    def boom(payload):
        raise RuntimeError("sdk down")

    svc = SignalService(store, auth, [TelegramChannel(BOT_TOKEN, "1", dead.client()),
                                      TelegramChannel(BOT_TOKEN, "2", flaky.client(), name="telegram2"),
                                      PushChannel(sender=boom), dash],
                        max_retries=3, backoff_seconds=0.5, sleep=sleeps.append, clock=clock)
    with caplog.at_level(logging.DEBUG):
        s = svc.create(proposal(clock()), tick(clock()), "mock")
    d = {r["channel"]: r for r in svc.get(s.id).deliveries}
    assert d["telegram"]["ok"] is False and d["telegram"]["attempts"] == 3 and "401" in d["telegram"]["error"]
    assert d["telegram2"]["ok"] is True and d["telegram2"]["attempts"] == 3
    assert d["push"]["ok"] is False and "RuntimeError" in d["push"]["error"]
    assert d["dashboard"]["ok"] is True and len(dash.peek()) == 1
    assert sleeps == [0.5, 1.0] * 3
    # secrets never appear in logs or stored delivery records
    assert BOT_TOKEN not in caplog.text
    assert BOT_TOKEN not in json.dumps(store.kv_get("signals"))


def test_transport_error_message_has_no_secret():
    def handler(req):
        raise httpx.ConnectError("boom " + str(req.url))

    ch = TelegramChannel(BOT_TOKEN, "1", httpx.Client(transport=httpx.MockTransport(handler)))
    now = datetime.now(timezone.utc)
    from gold_ai.notifications import Outgoing
    with pytest.raises(ChannelError) as ei:
        ch.send(Outgoing(Signal.from_proposal(proposal(now), tick(now), "mock"), "x", "id|h"))
    assert BOT_TOKEN not in str(ei.value)


def test_push_webhook_and_sender():
    rec = Recorder()
    now = datetime.now(timezone.utc)
    from gold_ai.notifications import Outgoing
    msg = Outgoing(Signal.from_proposal(proposal(now), tick(now), "mock"), "text", "sid|handle")
    PushChannel(webhook_url="https://push.example/hook", client=rec.client()).send(msg)
    body = json.loads(rec.requests[0].content)
    assert body["title"].startswith("SIGNAL ONLY") and body["data"]["actions"]["approve"] == "ap|sid|handle"
    got = []
    PushChannel(sender=got.append).send(msg)
    assert got[0]["data"]["signal_id"] == msg.signal.id
    with pytest.raises(ChannelError):
        PushChannel().send(msg)


def test_dashboard_approve_does_not_place_orders(store, auth, clock):
    dash = DashboardChannel()
    svc = make_service(store, auth, clock, [dash])
    s = svc.create(proposal(clock()), tick(clock()), "mock")
    item = dash.drain()[0]
    token = item["approval_token"]
    assert item["signal"]["id"] == s.id and dash.peek() == []
    assert svc.act(s.id, "approve", "forged.token").ok is False
    assert svc.act("nope", "approve", token).reason == "unknown signal"
    assert svc.act(s.id, "launch", token).ok is False
    res = svc.act(s.id, "approve", token, actor="owner")
    assert res.ok and res.execution_requested is True
    assert svc.get(s.id).status == SignalStatus.APPROVED and svc.get(s.id).acted_by == "owner"
    assert store.audit_log()[0]["detail"]["order_placed"] is False
    assert svc.act(s.id, "reject", token).reason == "signal already approved"


@pytest.mark.parametrize("action,status", [("reject", SignalStatus.REJECTED), ("ignore", SignalStatus.IGNORED),
                                           ("manual", SignalStatus.MANUAL)])
def test_other_actions(store, auth, clock, action, status):
    dash = DashboardChannel()
    svc = make_service(store, auth, clock, [dash])
    s = svc.create(proposal(clock()), tick(clock()), "mock")
    other = svc.create(proposal(clock()), tick(clock()), "mock")
    tokens = {i["signal"]["id"]: i["approval_token"] for i in dash.drain()}
    assert svc.act(s.id, action, tokens[other.id]).ok is False   # token bound to its own signal
    res = svc.act(s.id, action, tokens[s.id])
    assert res.ok and not res.execution_requested and svc.get(s.id).status == status
    assert [x.id for x in svc.list(status)] == [s.id]


def test_expiry(store, auth, clock):
    dash = DashboardChannel()
    svc = make_service(store, auth, clock, [dash])
    s1 = svc.create(proposal(clock(), valid=30), tick(clock()), "mock")
    s2 = svc.create(proposal(clock(), valid=30), tick(clock()), "mock")
    tokens = {i["signal"]["id"]: i["approval_token"] for i in dash.drain()}
    clock.now += timedelta(seconds=31)
    res = svc.act(s1.id, "approve", tokens[s1.id])
    assert not res.ok and res.reason == "signal expired" and not res.execution_requested
    assert svc.get(s1.id).status == SignalStatus.EXPIRED
    assert svc.expire_stale() == [s2.id]
    assert svc.list(SignalStatus.PENDING) == []


def test_callback_rejects_tampering(store, auth, clock):
    rec = Recorder()
    svc = make_service(store, auth, clock, [TelegramChannel(BOT_TOKEN, "1", rec.client())])
    s = svc.create(proposal(clock()), tick(clock()), "mock")
    assert svc.handle_callback("garbage", "x").reason == "malformed callback"
    assert svc.handle_callback(f"ap|{s.id}|0000000000000000", "x").ok is False
    assert svc.handle_callback("ap|unknown|0000000000000000", "x").ok is False
    assert svc.get(s.id).status == SignalStatus.PENDING


def test_channels_from_settings():
    base = Settings(secret_key="test-secret-key-0123456789")
    assert [c.name for c in channels_from_settings(base)] == ["dashboard"]
    full = base.model_copy(update={"telegram_bot_token": BOT_TOKEN, "telegram_chat_id": "1",
                                   "whatsapp_token": WA_TOKEN, "whatsapp_phone_id": "p",
                                   "whatsapp_recipient": "r"})
    assert [c.name for c in channels_from_settings(full)] == ["dashboard", "telegram", "whatsapp"]
