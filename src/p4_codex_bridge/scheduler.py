"""Persistent resource queue for Codex work.

This layer decides technical eligibility only. It never assigns business priority.
Queued prompts are kept in a private payload table until dispatch/cancellation;
they are never returned by discovery APIs or written to logs.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import QueueFullError
from .models import RunStatus


@dataclass(frozen=True)
class RuntimeLimits:
    global_max_active: int = 4
    app_server_max_active: int = 4
    exec_max_active: int = 2
    max_active_threads: int = 16
    max_queue_size: int = 100
    profile_limits: dict[str, int] = field(default_factory=lambda: {"analysis": 4, "planning": 2, "implementation": 1, "validation": 2, "documentation": 1})

    def __post_init__(self) -> None:
        values = (self.global_max_active, self.app_server_max_active, self.exec_max_active, self.max_active_threads, self.max_queue_size, *self.profile_limits.values())
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
            raise ValueError("runtime limits must be positive integers")


def canonical_workspace(path: str | Path) -> str:
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace must be an existing directory")
    # normcase folds case and separators on Windows; normpath removes trailing dot segments.
    return os.path.normcase(os.path.normpath(str(root))).casefold() if os.name == "nt" else os.path.normpath(str(root))


class ResourceScheduler:
    """SQLite-backed FIFO queue with atomic slot/workspace claims."""
    ACTIVE = (RunStatus.RUNNING.value, RunStatus.WAITING_APPROVAL.value)
    QUEUED = (RunStatus.QUEUED.value, RunStatus.WAITING_FOR_SLOT.value)
    TERMINAL = (RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.INTERRUPTED.value,
                RunStatus.CANCELLED.value, RunStatus.LOST.value, RunStatus.STOPPED.value, RunStatus.TIMED_OUT.value)

    def __init__(self, database: str | Path, limits: RuntimeLimits | None = None, *, instance_id: str | None = None):
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self.limits = limits or RuntimeLimits()
        self.instance_id = instance_id or str(uuid.uuid4())
        self._lock = threading.RLock()
        self._init()
        saved = self.get_persisted_limits()
        if saved:
            self.limits = RuntimeLimits(**saved)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def _init(self) -> None:
        with self._connect() as db:
            db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS scheduler_runs(
              bridge_run_id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, thread_id TEXT NOT NULL,
              backend TEXT NOT NULL, profile TEXT NOT NULL, workspace TEXT NOT NULL,
              access_mode TEXT NOT NULL CHECK(access_mode IN ('READ','WRITE')),
              status TEXT NOT NULL, submitted_at TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0,
              waiting_reason TEXT, blocked_by_run_id TEXT, owner_instance_id TEXT NOT NULL,
              started_at TEXT, finished_at TEXT, error TEXT, agent_metadata_json TEXT NOT NULL DEFAULT '{}',
              process_pid INTEGER, process_identity TEXT, worker_pid INTEGER, worker_identity TEXT, native_session_id TEXT,
              cancel_requested INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS scheduler_payloads(bridge_run_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
              FOREIGN KEY(bridge_run_id) REFERENCES scheduler_runs(bridge_run_id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS workspace_locks(workspace TEXT NOT NULL, bridge_run_id TEXT PRIMARY KEY,
              mode TEXT NOT NULL, owner_instance_id TEXT NOT NULL, acquired_at TEXT NOT NULL,
              FOREIGN KEY(bridge_run_id) REFERENCES scheduler_runs(bridge_run_id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS runtime_settings(name TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS scheduler_order ON scheduler_runs(status, priority DESC, submitted_at, bridge_run_id);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(scheduler_runs)")}
            if "agent_metadata_json" not in columns:
                db.execute("ALTER TABLE scheduler_runs ADD COLUMN agent_metadata_json TEXT NOT NULL DEFAULT '{}'")
            for name, definition in {"process_pid": "INTEGER", "process_identity": "TEXT", "worker_pid": "INTEGER", "worker_identity": "TEXT", "native_session_id": "TEXT", "cancel_requested": "INTEGER NOT NULL DEFAULT 0"}.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE scheduler_runs ADD COLUMN {name} {definition}")
            db.execute("COMMIT")

    def get_persisted_limits(self) -> dict[str, Any] | None:
        with self._connect() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_settings'").fetchone()
            if not exists: return None
            row = db.execute("SELECT value_json FROM runtime_settings WHERE name='limits'").fetchone()
            return json.loads(row[0]) if row else None

    def persist_limits(self, limits: RuntimeLimits) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO runtime_settings(name,value_json) VALUES('limits',?) ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json",
                       (json.dumps({**limits.__dict__, "profile_limits": limits.profile_limits}, sort_keys=True),))

    def submit(self, *, turn_id: str, thread_id: str, backend: str, profile: str, workspace: str | Path,
               prompt: str, access_mode: str = "READ", priority: int = 0, metadata: dict[str, Any] | None = None,
               bridge_run_id: str | None = None, submitted_at: str, transaction_hook=None, queue_limit: int | None = None,
               payload_data: dict[str, Any] | None = None) -> dict[str, Any]:
        mode = access_mode.upper()
        if mode not in {"READ", "WRITE"}: raise ValueError("access_mode must be READ or WRITE")
        if not isinstance(prompt, str) or not prompt.strip(): raise ValueError("prompt is required")
        if isinstance(priority, bool) or not isinstance(priority, int): raise ValueError("priority must be an integer")
        canonical = canonical_workspace(workspace)
        run_id = bridge_run_id or "br_" + uuid.uuid4().hex[:12]
        if len(prompt.encode("utf-8")) > 1024 * 1024:
            raise ValueError("prompt exceeds the 1 MiB scheduler payload limit")
        full_payload = {**(payload_data or {}), "prompt": prompt}
        payload = json.dumps(full_payload, ensure_ascii=False)
        if len(payload.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("scheduled request exceeds the 2 MiB payload limit")
        from .registry import _clean_metadata
        safe_metadata = _clean_metadata(metadata or {})
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute("SELECT COUNT(*) FROM scheduler_runs WHERE status IN ('QUEUED','WAITING_FOR_SLOT')").fetchone()[0]
            max_pending = min(self.limits.max_queue_size, queue_limit) if queue_limit is not None else self.limits.max_queue_size
            if pending >= max_pending:
                db.rollback(); raise QueueFullError("QUEUE_LIMIT: persistent scheduler queue is full")
            db.execute("INSERT INTO scheduler_runs(bridge_run_id,turn_id,thread_id,backend,profile,workspace,access_mode,status,submitted_at,priority,owner_instance_id,agent_metadata_json) VALUES(?,?,?,?,?,?,?,'QUEUED',?,?,?,?)",
                       (run_id, turn_id, thread_id, backend, profile, canonical, mode, submitted_at, priority, self.instance_id, json.dumps(safe_metadata, ensure_ascii=False)))
            db.execute("INSERT INTO scheduler_payloads VALUES(?,?)", (run_id, payload))
            if transaction_hook is not None: transaction_hook(db, run_id)
            db.commit()
        return self.get(run_id)

    def _reason(self, db: sqlite3.Connection, row: sqlite3.Row, limits: RuntimeLimits) -> tuple[str | None, str | None]:
        counts = db.execute("SELECT backend,profile,COUNT(*) n FROM scheduler_runs WHERE status IN ('RUNNING','WAITING_APPROVAL') GROUP BY backend,profile").fetchall()
        active = sum(int(item["n"]) for item in counts)
        if active >= limits.global_max_active: return "GLOBAL_LIMIT", None
        active_threads = db.execute("SELECT COUNT(DISTINCT thread_id) FROM scheduler_runs WHERE status IN ('RUNNING','WAITING_APPROVAL')").fetchone()[0]
        active_thread_ids = {x[0] for x in db.execute("SELECT DISTINCT thread_id FROM scheduler_runs WHERE status IN ('RUNNING','WAITING_APPROVAL')")}
        if row["thread_id"] in active_thread_ids:
            blocker = db.execute("SELECT bridge_run_id FROM scheduler_runs WHERE thread_id=? AND status IN ('RUNNING','WAITING_APPROVAL') ORDER BY started_at LIMIT 1", (row["thread_id"],)).fetchone()
            return "THREAD_LIMIT", blocker[0] if blocker else None
        if row["thread_id"] not in active_thread_ids and active_threads >= limits.max_active_threads:
            return "THREAD_LIMIT", None
        backend_active = sum(int(x["n"]) for x in counts if x["backend"] == row["backend"])
        backend_limit = limits.app_server_max_active if row["backend"] == "app-server" else limits.exec_max_active
        if backend_active >= backend_limit: return "BACKEND_LIMIT", None
        profile_active = sum(int(x["n"]) for x in counts if x["profile"] == row["profile"])
        if profile_active >= limits.profile_limits.get(row["profile"], limits.global_max_active): return "PROFILE_LIMIT", None
        lock = db.execute("SELECT bridge_run_id,mode FROM workspace_locks WHERE workspace=? AND (?='WRITE' OR mode='WRITE') ORDER BY acquired_at LIMIT 1", (row["workspace"], row["access_mode"])).fetchone()
        if lock:
            return "WORKSPACE_LOCK", lock["bridge_run_id"]
        return None, None

    def dispatch(self, *, limits: RuntimeLimits | None = None, limit: int | None = None,
                 backend: str | None = None) -> list[dict[str, Any]]:
        """Atomically claim eligible queue entries and return payloads to the owner."""
        limits = limits or self.limits
        claimed: list[dict[str, Any]] = []
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if backend:
                rows = db.execute("SELECT * FROM scheduler_runs WHERE status IN ('QUEUED','WAITING_FOR_SLOT') AND backend=? ORDER BY priority DESC,submitted_at,bridge_run_id", (backend,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM scheduler_runs WHERE status IN ('QUEUED','WAITING_FOR_SLOT') ORDER BY priority DESC,submitted_at,bridge_run_id").fetchall()
            queued_count = len(rows)
            for row in rows:
                if limit is not None and len(claimed) >= limit: break
                reason, blocked = self._reason(db, row, limits)
                if reason:
                    db.execute("UPDATE scheduler_runs SET status='WAITING_FOR_SLOT',waiting_reason=?,blocked_by_run_id=? WHERE bridge_run_id=?", (reason, blocked, row["bridge_run_id"]))
                    continue
                payload_row = db.execute("SELECT payload_json FROM scheduler_payloads WHERE bridge_run_id=?", (row["bridge_run_id"],)).fetchone()
                if not payload_row: continue
                now = datetime.now(timezone.utc).isoformat()
                db.execute("UPDATE scheduler_runs SET status='RUNNING',started_at=?,waiting_reason=NULL,blocked_by_run_id=NULL WHERE bridge_run_id=? AND status IN ('QUEUED','WAITING_FOR_SLOT')", (now, row["bridge_run_id"]))
                db.execute("INSERT INTO workspace_locks VALUES(?,?,?,?,?)", (row["workspace"], row["bridge_run_id"], row["access_mode"], self.instance_id, now))
                db.execute("DELETE FROM scheduler_payloads WHERE bridge_run_id=?", (row["bridge_run_id"],))
                claimed.append({**dict(row), "status": "RUNNING", "payload": json.loads(payload_row[0]), "queue_position": None})
            db.commit()
        return claimed

    def finish(self, run_id: str, status: str, *, finished_at: str, error: str | None = None) -> None:
        if status not in self.TERMINAL: raise ValueError("invalid terminal scheduler status")
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM scheduler_runs WHERE bridge_run_id=?", (run_id,)).fetchone()
            if row is None: db.rollback(); raise KeyError(run_id)
            if row[0] in self.TERMINAL: db.rollback(); return
            db.execute("UPDATE scheduler_runs SET status=?,finished_at=?,error=?,waiting_reason=NULL,blocked_by_run_id=NULL WHERE bridge_run_id=?", (status, finished_at, error, run_id))
            db.execute("DELETE FROM workspace_locks WHERE bridge_run_id=?", (run_id,))
            db.execute("DELETE FROM scheduler_payloads WHERE bridge_run_id=?", (run_id,))
            db.commit()

    def reconcile_lost(self, run_id: str, status: str, *, finished_at: str, error: str | None = None) -> bool:
        """Correct a conservative LOST marker only after a matching remote terminal state is verified."""
        if status not in {RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.INTERRUPTED.value}:
            raise ValueError("remote reconciliation requires a terminal Codex turn status")
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("UPDATE scheduler_runs SET status=?,finished_at=?,error=? WHERE bridge_run_id=? AND status='LOST' AND error='manager restarted; remote outcome unknown'",
                                (status, finished_at, error, run_id))
            db.commit()
            return cursor.rowcount == 1

    def set_status(self, run_id: str, status: str) -> None:
        if status not in {"RUNNING", "WAITING_APPROVAL"}: raise ValueError("invalid active scheduler status")
        with self._connect() as db: db.execute("UPDATE scheduler_runs SET status=? WHERE bridge_run_id=? AND status IN ('RUNNING','WAITING_APPROVAL')", (status, run_id))

    def rekey_turn(self, run_id: str, turn_id: str) -> None:
        with self._connect() as db: db.execute("UPDATE scheduler_runs SET turn_id=? WHERE bridge_run_id=?", (turn_id, run_id))

    def set_process(self, run_id: str, *, process_pid: int | None = None, process_identity: str | None = None,
                    worker_pid: int | None = None, worker_identity: str | None = None,
                    native_session_id: str | None = None) -> None:
        values = {k: v for k, v in {"process_pid": process_pid, "process_identity": process_identity,
            "worker_pid": worker_pid, "worker_identity": worker_identity, "native_session_id": native_session_id}.items() if v is not None}
        if not values: return
        assignments = ",".join(f"{name}=?" for name in values)
        with self._connect() as db: db.execute(f"UPDATE scheduler_runs SET {assignments} WHERE bridge_run_id=?", (*values.values(), run_id))

    def reconcile_after_restart(self, *, finished_at: str, backend: str | None = None) -> list[str]:
        """Mark in-flight work lost; preserve queued payloads and never replay claimed work."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if backend:
                ids = [row[0] for row in db.execute("SELECT bridge_run_id FROM scheduler_runs WHERE status IN ('RUNNING','WAITING_APPROVAL') AND backend=?", (backend,))]
            else:
                ids = [row[0] for row in db.execute("SELECT bridge_run_id FROM scheduler_runs WHERE status IN ('RUNNING','WAITING_APPROVAL')")]
            db.executemany("UPDATE scheduler_runs SET status='LOST',finished_at=?,error='manager restarted; remote outcome unknown' WHERE bridge_run_id=?", [(finished_at, run_id) for run_id in ids])
            db.executemany("DELETE FROM workspace_locks WHERE bridge_run_id=?", [(run_id,) for run_id in ids])
            db.commit()
            return ids

    def cancel(self, run_id: str, *, finished_at: str) -> bool:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM scheduler_runs WHERE bridge_run_id=?", (run_id,)).fetchone()
            if row is None: db.rollback(); raise KeyError(run_id)
            if row[0] not in self.QUEUED: db.rollback(); return False
            db.execute("UPDATE scheduler_runs SET status='CANCELLED',finished_at=?,waiting_reason=NULL,blocked_by_run_id=NULL WHERE bridge_run_id=?", (finished_at, run_id))
            db.execute("DELETE FROM scheduler_payloads WHERE bridge_run_id=?", (run_id,))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_turns'").fetchone():
                db.execute("UPDATE runtime_turns SET status='CANCELLED',finished_at=? WHERE bridge_run_id=?", (finished_at, run_id))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='turn_events'").fetchone():
                item = db.execute("SELECT turn_id,thread_id FROM scheduler_runs WHERE bridge_run_id=?", (run_id,)).fetchone()
                payload = json.dumps({"type": "CANCELLED", "timestamp": finished_at, "thread_id": item[1], "turn_id": item[0], "data": {}}, separators=(",", ":"))
                db.execute("INSERT INTO turn_events(thread_id,turn_id,event_type,timestamp,payload_json,bridge_run_id) VALUES(?,?,?,?,?,?)", (item[1], item[0], "CANCELLED", finished_at, payload, run_id))
            db.commit()
            return True

    def request_cancel(self, run_id: str) -> bool:
        """Persist cancellation intent for a claimed job; never signals a process by PID here."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,cancel_requested FROM scheduler_runs WHERE bridge_run_id=?", (run_id,)).fetchone()
            if row is None: db.rollback(); raise KeyError(run_id)
            if row[0] not in self.ACTIVE: db.rollback(); return False
            if row[1]: db.rollback(); return True
            db.execute("UPDATE scheduler_runs SET cancel_requested=1 WHERE bridge_run_id=?", (run_id,))
            db.commit()
            return True

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM scheduler_runs WHERE bridge_run_id=?", (run_id,)).fetchone()
            if row is None: return None
            result = dict(row)
            if row["status"] in {"QUEUED", "WAITING_FOR_SLOT"}:
                candidates = db.execute("SELECT bridge_run_id FROM scheduler_runs WHERE status IN ('QUEUED','WAITING_FOR_SLOT') ORDER BY priority DESC,submitted_at,bridge_run_id").fetchall()
                result["queue_position"] = next((i for i, candidate in enumerate(candidates, 1) if candidate[0] == run_id), None)
            else: result["queue_position"] = None
            return result

    def list_runs(self, *, active: bool = False) -> list[dict[str, Any]]:
        with self._connect() as db:
            ids = [row[0] for row in db.execute("SELECT bridge_run_id FROM scheduler_runs ORDER BY priority DESC,submitted_at,bridge_run_id")]
        rows = [self.get(run_id) for run_id in ids]
        return [row for row in rows if row and (not active or row["status"] in {"QUEUED", "WAITING_FOR_SLOT", *self.ACTIVE})]

    def resources(self, limits: RuntimeLimits | None = None) -> dict[str, Any]:
        limits = limits or self.limits
        rows = self.list_runs()
        active = [row for row in rows if row["status"] in self.ACTIVE]
        queued = [row for row in rows if row["status"] in {"QUEUED", "WAITING_FOR_SLOT"}]
        return {"global": {"used": len(active), "limit": limits.global_max_active, "free": max(0, limits.global_max_active-len(active))},
                "backends": {name: {"used": sum(x["backend"] == name for x in active), "limit": cap} for name, cap in (("app-server", limits.app_server_max_active), ("exec", limits.exec_max_active))},
                "profiles": {name: {"used": sum(x["profile"] == name for x in active), "limit": cap} for name, cap in limits.profile_limits.items()},
                "workspace_locks": [{"workspace": x["workspace"], "mode": x["access_mode"], "bridge_run_id": x["bridge_run_id"]} for x in active],
                "queue_length": len(queued), "queued_runs": queued, "active_runs": active}
