"""Owner-controlled backup, verified restore and archival export.

- SQLite: online, consistent copy via the sqlite3 backup API (safe with WAL), timestamped,
  with a JSON manifest holding the SHA-256 checksum, size, integrity check and row counts.
- PostgreSQL: `build_pg_dump_command` returns the pg_dump argv and environment (the
  password goes in PGPASSWORD, never on the command line); execution is opt-in.
- Restore always writes to a NEW path (never over the live database) and is verified
  against the manifest checksum, PRAGMA integrity_check and table row counts.
- Archival export writes one memory domain to JSONL. It never deletes anything.

Every action requires the owner role and is written to the audit log.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .domain import MemoryDomain
from .memory.store import MemoryStore

MANIFEST_SUFFIX = ".manifest.json"


def _require_owner(user) -> str:
    if getattr(user, "role", None) != "owner":
        raise PermissionError("backup / restore / archival are owner-only actions")
    return user.username


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sqlite_path_from_url(url: str) -> str:
    if not url.startswith("sqlite:///") or url.startswith("sqlite:///:memory:"):
        raise ValueError(f"not a file-backed SQLite URL: {url}")
    return url.removeprefix("sqlite:///")


def _sqlite_info(path: str) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()
    return {"integrity_check": integrity, "table_counts": counts}


def build_pg_dump_command(url: str, out_path: str) -> tuple[list[str], dict[str, str]]:
    """Return (argv, extra_env) for a custom-format pg_dump. Password is passed via env only."""
    u = urlparse(url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://",
                                                                                "postgresql://"))
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError(f"not a PostgreSQL URL: {url}")
    argv = ["pg_dump", "--format=custom", "--no-owner", "--file", out_path]
    if u.hostname:
        argv += ["--host", u.hostname]
    if u.port:
        argv += ["--port", str(u.port)]
    if u.username:
        argv += ["--username", unquote(u.username)]
    argv.append(u.path.lstrip("/"))
    env = {"PGPASSWORD": unquote(u.password)} if u.password else {}
    return argv, env


class BackupService:
    def __init__(self, store: MemoryStore, database_url: str, backup_dir: str | os.PathLike = "./data/backups"):
        self.store = store
        self.url = database_url
        self.backup_dir = Path(backup_dir)

    # -- backup -----------------------------------------------------------------------
    def backup(self, owner, *, dest_dir: str | os.PathLike | None = None, run_pg_dump: bool = False) -> dict:
        actor = _require_owner(owner)
        dest = Path(dest_dir or self.backup_dir)
        dest.mkdir(parents=True, exist_ok=True)
        if self.url.startswith("sqlite"):
            src = sqlite_path_from_url(self.url)
            out = dest / f"gold_ai-{_stamp()}.db"
            if out.exists():
                raise FileExistsError(out)
            s = sqlite3.connect(src)
            d = sqlite3.connect(out)
            try:
                with d:
                    s.backup(d)
            finally:
                d.close()
                s.close()
            manifest = {"kind": "sqlite", "file": out.name, "path": str(out.resolve()),
                        "sha256": sha256_file(out), "size": out.stat().st_size,
                        "created_at": datetime.now(timezone.utc).isoformat(), "source": os.path.abspath(src),
                        "created_by": actor, **_sqlite_info(str(out))}
            if manifest["integrity_check"] != "ok":
                raise RuntimeError(f"backup failed integrity check: {manifest['integrity_check']}")
        else:
            out = dest / f"gold_ai-{_stamp()}.pgdump"
            argv, env = build_pg_dump_command(self.url, str(out))
            manifest = {"kind": "postgresql", "file": out.name, "path": str(out.resolve()), "command": argv,
                        "created_at": datetime.now(timezone.utc).isoformat(), "created_by": actor,
                        "status": "command_built"}
            if run_pg_dump:
                subprocess.run(argv, env={**os.environ, **env}, check=True)
                manifest.update(status="completed", sha256=sha256_file(out), size=out.stat().st_size)
        mpath = out.with_name(out.name + MANIFEST_SUFFIX)
        mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        manifest["manifest_path"] = str(mpath)
        self.store.audit(actor, "backup_created", {k: v for k, v in manifest.items() if k != "table_counts"})
        return manifest

    # -- verify / restore ---------------------------------------------------------------
    @staticmethod
    def load_manifest(backup_path: str | os.PathLike) -> dict:
        p = Path(backup_path)
        return json.loads(p.with_name(p.name + MANIFEST_SUFFIX).read_text())

    def verify(self, backup_path: str | os.PathLike) -> dict:
        p = Path(backup_path)
        m = self.load_manifest(p)
        problems = []
        if not p.exists():
            problems.append("backup file missing")
        else:
            if sha256_file(p) != m.get("sha256"):
                problems.append("checksum mismatch")
            if m.get("kind") == "sqlite":
                info = _sqlite_info(str(p))
                if info["integrity_check"] != "ok":
                    problems.append(f"integrity_check: {info['integrity_check']}")
                if info["table_counts"] != m.get("table_counts"):
                    problems.append("table row counts differ from manifest")
        return {"ok": not problems, "problems": problems, "manifest": m}

    def restore(self, owner, backup_path: str | os.PathLike, target_path: str | os.PathLike) -> dict:
        """Restore a SQLite backup to a NEW file. Refuses to overwrite anything (including the live DB)."""
        actor = _require_owner(owner)
        target = Path(target_path)
        if target.exists():
            raise FileExistsError(f"restore target exists (restores never overwrite): {target}")
        if self.url.startswith("sqlite") and target.resolve() == Path(sqlite_path_from_url(self.url)).resolve():
            raise ValueError("restore target is the live database")
        v = self.verify(backup_path)
        if not v["ok"]:
            self.store.audit(actor, "restore_refused", {"backup": str(backup_path), "problems": v["problems"]})
            raise ValueError(f"backup failed verification: {v['problems']}")
        if v["manifest"].get("kind") != "sqlite":
            raise NotImplementedError("PostgreSQL restore must be run with pg_restore by the owner")
        target.parent.mkdir(parents=True, exist_ok=True)
        s = sqlite3.connect(f"file:{Path(backup_path)}?mode=ro", uri=True)
        d = sqlite3.connect(target)
        try:
            with d:
                s.backup(d)
        finally:
            d.close()
            s.close()
        info = _sqlite_info(str(target))
        ok = info["integrity_check"] == "ok" and info["table_counts"] == v["manifest"]["table_counts"]
        result = {"ok": ok, "target": str(target.resolve()), "backup": str(backup_path), **info}
        self.store.audit(actor, "restore_completed" if ok else "restore_verification_failed",
                         {k: v for k, v in result.items() if k != "table_counts"})
        if not ok:
            raise RuntimeError("restored database failed verification")
        return result

    # -- archival export ----------------------------------------------------------------
    def export_domain(self, owner, domain: MemoryDomain, dest_dir: str | os.PathLike | None = None) -> dict:
        """Write every trade of one memory domain to JSONL (+ manifest). Deletes nothing."""
        actor = _require_owner(owner)
        dest = Path(dest_dir or self.backup_dir)
        dest.mkdir(parents=True, exist_ok=True)
        before = self.store.count_trades(domain)
        trades = self.store.load_trades(domain)
        out = dest / f"archive-{domain.value}-{_stamp()}.jsonl"
        with open(out, "x", encoding="utf-8") as f:
            for t in trades:
                d = asdict(t)
                d["side"] = t.side.value
                d["exit_reason"] = t.exit_reason.value if t.exit_reason else None
                f.write(json.dumps(d, default=str, sort_keys=True) + "\n")
        after = self.store.count_trades(domain)
        manifest = {"kind": "archive_export", "domain": domain.value, "file": out.name, "path": str(out.resolve()),
                    "records": len(trades), "sha256": sha256_file(out), "created_by": actor,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_count_before": before, "source_count_after": after,
                    "note": "export only; no records were deleted"}
        out.with_name(out.name + MANIFEST_SUFFIX).write_text(json.dumps(manifest, indent=2, sort_keys=True))
        self.store.audit(actor, "memory_archived", manifest)
        return manifest
