import json
from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.backup import BackupService, build_pg_dump_command, sha256_file
from gold_ai.domain import MemoryDomain, Side, SimTrade
from gold_ai.memory.store import MemoryStore
from gold_ai.security.auth import User

OWNER, OPERATOR = User("owner", "owner"), User("op", "operator")
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def trades(n):
    return [SimTrade(f"h{i}", "mock", "a", "XAUUSD", Side.BUY, 0.1, T0 + timedelta(minutes=i), 2400, 2397, 2404,
                     "s", "m", exit_time=T0 + timedelta(minutes=i, seconds=30), net_pnl=float(i),
                     context={"regime": "range"}) for i in range(n)]


@pytest.fixture
def svc(settings, store, tmp_path):
    store.save_trades(MemoryDomain.HISTORICAL, trades(7))
    store.kv_set("x", {"a": 1})
    return BackupService(store, settings.database_url, tmp_path / "backups")


def test_backup_is_owner_only(svc):
    with pytest.raises(PermissionError):
        svc.backup(OPERATOR)
    with pytest.raises(PermissionError):
        svc.export_domain(OPERATOR, MemoryDomain.HISTORICAL)


def test_backup_manifest_and_verify(svc, tmp_path):
    m = svc.backup(OWNER)
    path = tmp_path / "backups" / m["file"]
    assert path.exists() and m["sha256"] == sha256_file(path)
    assert m["integrity_check"] == "ok" and m["table_counts"]["mem_a_historical_trades"] == 7
    assert json.loads((tmp_path / "backups" / (m["file"] + ".manifest.json")).read_text())["sha256"] == m["sha256"]
    assert svc.verify(path)["ok"]
    assert any(a["action"] == "backup_created" for a in svc.store.audit_log())
    # tampering is detected and restore refuses it
    with open(path, "ab") as f:
        f.write(b"tamper")
    v = svc.verify(path)
    assert not v["ok"] and "checksum mismatch" in v["problems"]
    with pytest.raises(ValueError):
        svc.restore(OWNER, path, tmp_path / "restored.db")
    assert not (tmp_path / "restored.db").exists()


def test_restore_to_new_path_only(svc, settings, tmp_path):
    m = svc.backup(OWNER)
    path = tmp_path / "backups" / m["file"]
    target = tmp_path / "restore" / "r.db"
    res = svc.restore(OWNER, path, target)
    assert res["ok"] and res["table_counts"] == m["table_counts"]
    restored = MemoryStore(f"sqlite:///{target}")
    assert restored.count_trades(MemoryDomain.HISTORICAL) == 7 and restored.kv_get("x") == {"a": 1}
    with pytest.raises(FileExistsError):
        svc.restore(OWNER, path, target)
    with pytest.raises(FileExistsError):
        svc.restore(OWNER, path, settings.database_url.removeprefix("sqlite:///"))
    with pytest.raises(PermissionError):
        svc.restore(OPERATOR, path, tmp_path / "other.db")


def test_export_domain_jsonl_deletes_nothing(svc, tmp_path):
    m = svc.export_domain(OWNER, MemoryDomain.HISTORICAL)
    lines = (tmp_path / "backups" / m["file"]).read_text().splitlines()
    assert len(lines) == m["records"] == 7
    rec = json.loads(lines[0])
    assert rec["trade_id"] == "h0" and rec["side"] == "BUY" and rec["context"] == {"regime": "range"}
    assert m["source_count_before"] == m["source_count_after"] == 7
    assert svc.store.count_trades(MemoryDomain.HISTORICAL) == 7
    assert svc.export_domain(OWNER, MemoryDomain.REAL)["records"] == 0


def test_pg_dump_command_keeps_password_off_argv(store, tmp_path):
    argv, env = build_pg_dump_command("postgresql+psycopg://gold:s3cr%40t@db.local:5433/goldai", "/b/x.pgdump")
    assert argv[0] == "pg_dump" and "--format=custom" in argv and argv[-1] == "goldai"
    assert ["--host", "db.local"] == argv[argv.index("--host"):argv.index("--host") + 2]
    assert "5433" in argv and "gold" in argv
    assert not any("s3cr" in a for a in argv) and env == {"PGPASSWORD": "s3cr@t"}
    with pytest.raises(ValueError):
        build_pg_dump_command("mysql://x/y", "o")
    svc = BackupService(store, "postgresql://gold:pw@h/goldai", tmp_path)
    m = svc.backup(OWNER)  # builds the command, does not execute it
    assert m["status"] == "command_built" and "pw" not in " ".join(m["command"])
