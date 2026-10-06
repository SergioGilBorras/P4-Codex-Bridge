from __future__ import annotations

"""Resident app-server owner and local lifecycle registry.

The manager owns one stdio app-server process. It deliberately does not retry
turns after a crash: a caller must inspect/reconcile the recorded lifecycle.
"""

import hashlib
import json
import logging
import os
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import __version__
from .events import is_tool_item
from .runtime import codex_environment, redact, redact_structured, resolve_codex_command
from .models import RunStatus

logger = logging.getLogger("p4_codex_bridge.runtime")


from .errors import CapabilityUnavailableError


class RuntimeState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    STOPPING = "STOPPING"
    CRASHED = "CRASHED"


def request_app_server_cancel(database_path: str | Path, bridge_run_id: str, *, timeout: float = 5) -> None:
    """Request cancellation from the process that owns the shared app-server stream."""
    from contextlib import closing
    import sqlite3
    request_id = str(uuid.uuid4())
    with closing(sqlite3.connect(database_path, timeout=5)) as db, db:
        db.execute("INSERT INTO runtime_control_requests(request_id,bridge_run_id,action,status,error,created_at) VALUES(?,?,'interrupt','PENDING',NULL,?)", (request_id, bridge_run_id, _now()))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with closing(sqlite3.connect(database_path, timeout=2)) as db:
            row = db.execute("SELECT status,error FROM runtime_control_requests WHERE request_id=?", (request_id,)).fetchone()
        if row and row[0] == "COMPLETED":
            with closing(sqlite3.connect(database_path, timeout=2)) as db, db:
                db.execute("DELETE FROM runtime_control_requests WHERE request_id=?", (request_id,))
            return
        if row and row[0] == "FAILED":
            with closing(sqlite3.connect(database_path, timeout=2)) as db, db:
                db.execute("DELETE FROM runtime_control_requests WHERE request_id=?", (request_id,))
            raise RuntimeError(row[1] or "app-server cancellation failed")
        time.sleep(0.05)
    with closing(sqlite3.connect(database_path, timeout=2)) as db, db:
        db.execute("DELETE FROM runtime_control_requests WHERE request_id=? AND status='PENDING'", (request_id,))
    raise TimeoutError("app-server runtime did not accept cancellation before timeout")


def notify_app_server_capacity_change(database_path: str | Path) -> None:
    """Wake the active runtime after an exec run releases shared resources."""
    from contextlib import closing
    import sqlite3
    request_id = str(uuid.uuid4())
    with closing(sqlite3.connect(database_path, timeout=5)) as db, db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_control_requests'").fetchone()
        if exists:
            db.execute("INSERT INTO runtime_control_requests(request_id,bridge_run_id,action,status,error,created_at) VALUES(?, '', 'dispatch', 'PENDING', NULL, ?)", (request_id, _now()))


TurnState = RunStatus


_TRANSITIONS = {
    TurnState.CREATED: {TurnState.SUBMITTED, TurnState.QUEUED, TurnState.RUNNING, TurnState.FAILED},
    TurnState.SUBMITTED: {TurnState.QUEUED, TurnState.FAILED, TurnState.CANCELLED},
    TurnState.QUEUED: {TurnState.WAITING_FOR_SLOT, TurnState.RUNNING, TurnState.FAILED, TurnState.LOST, TurnState.CANCELLED},
    TurnState.WAITING_FOR_SLOT: {TurnState.RUNNING, TurnState.FAILED, TurnState.LOST, TurnState.CANCELLED},
    TurnState.RUNNING: {TurnState.WAITING_APPROVAL, TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED, TurnState.LOST, TurnState.UNKNOWN},
    TurnState.WAITING_APPROVAL: {TurnState.RUNNING, TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED, TurnState.LOST, TurnState.UNKNOWN},
    TurnState.UNKNOWN: {TurnState.COMPLETED, TurnState.FAILED, TurnState.LOST},
}


@dataclass
class ManagedThread:
    thread_id: str
    cwd: str
    profile: str
    model: str | None
    permissions: dict[str, Any]
    config_policy: str
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    status: str = "IDLE"
    agent_metadata: dict[str, Any] = field(default_factory=dict)
    server_id: str = ""


@dataclass
class ManagedTurn:
    turn_id: str
    thread_id: str
    status: TurnState
    started_at: str
    model: str | None = None
    finished_at: str | None = None
    error: str | None = None
    final_text: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    bridge_run_id: str = ""
    agent_metadata: dict[str, Any] = field(default_factory=dict)
    announce_run: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _SingletonLock:
    """OS-released advisory lock; metadata is informational, never authority."""
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                if self.path.stat().st_size == 0:
                    self.file.write(b" "); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.file.close(); self.file = None
            raise RuntimeError("another P4-Codex-Bridge runtime holds the singleton lock") from exc
        self.file.seek(0); self.file.truncate()
        self.file.write(json.dumps({"pid": os.getpid(), "instance_id": str(uuid.uuid4()), "started_at": _now()}).encode())
        self.file.flush()

    def release(self) -> None:
        if self.file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0); msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close(); self.file = None


class CodexRuntimeManager:
    """Owns a single app-server process and multiplexes JSON-RPC requests/events."""

    def __init__(self, *, cwd: str | Path, database_path: str | Path | None = None, lock_path: str | Path | None = None,
                 max_threads: int = 8, max_active_turns: int = 1, max_pending_requests: int = 64,
                 startup_timeout: float = 15, command: list[str] | None = None, runtime_limits=None):
        root = Path(cwd).expanduser().resolve(strict=True)
        if not root.is_dir(): raise ValueError("cwd must be an existing directory")
        for name, value, minimum in (("max_threads", max_threads, 1), ("max_active_turns", max_active_turns, 1), ("max_pending_requests", max_pending_requests, 1)):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum: raise ValueError(f"{name} must be a positive integer")
        if database_path is None:
            configured_state = os.environ.get("P4_CODEX_BRIDGE_STATE_DIR")
            if configured_state:
                state_root = Path(configured_state).expanduser()
            elif os.name == "nt":
                state_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "p4-codex-bridge"
            else:
                state_root = Path.home() / ".local" / "state" / "p4-codex-bridge"
            database_path = state_root / "runs.sqlite3"
        self.cwd, self.database_path = root, Path(database_path).expanduser().resolve()
        self.lock_path = Path(lock_path).resolve() if lock_path else self.database_path.with_suffix(".lock")
        self.max_threads, self.max_active_turns, self.max_pending_requests = max_threads, max_active_turns, max_pending_requests
        from .scheduler import ResourceScheduler, RuntimeLimits
        initial_limits = runtime_limits or RuntimeLimits(global_max_active=max_active_turns, app_server_max_active=max_active_turns, max_active_threads=max_threads)
        if initial_limits.max_queue_size > max_pending_requests:
            from dataclasses import replace
            initial_limits = replace(initial_limits, max_queue_size=max_pending_requests)
        self.runtime_limits = initial_limits
        self.scheduler = ResourceScheduler(self.database_path, self.runtime_limits, instance_id=str(uuid.uuid4()))
        if runtime_limits is None and self.scheduler.get_persisted_limits():
            self.runtime_limits = self.scheduler.limits
        else:
            self.scheduler.persist_limits(self.runtime_limits)
        if self.runtime_limits.max_queue_size > max_pending_requests:
            from dataclasses import replace
            self.runtime_limits = replace(self.runtime_limits, max_queue_size=max_pending_requests)
            self.scheduler.persist_limits(self.runtime_limits)
        self.scheduler.limits = self.runtime_limits
        self.startup_timeout = startup_timeout
        self.command = list(command) if command else resolve_codex_command() + ["app-server", "--listen", "stdio://"]
        self.instance_id = str(uuid.uuid4())
        self.scheduler.instance_id = self.instance_id
        self.process: subprocess.Popen[bytes] | None = None
        self.protocol_version: str | None = None
        self.server_info: dict[str, Any] = {}
        self.state = RuntimeState.STOPPED
        self.threads: dict[str, ManagedThread] = {}
        self.turns: dict[str, ManagedTurn] = {}
        self._pending: dict[int, queue.Queue] = {}
        self._next_id = 0
        self._write_lock = threading.Lock(); self._lock = threading.RLock()
        self._reader: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._background_threads: set[threading.Thread] = set()
        self._background_threads_lock = threading.Lock()
        self._control_stop = threading.Event()
        self._control_thread: threading.Thread | None = None
        self._singleton = _SingletonLock(self.lock_path)
        self._active = 0; self._queued = 0; self._received = 0; self._protocol_errors = 0
        self._max_observed_concurrency = 0
        self._completed = 0; self._failed = 0; self._restarts = 0; self._crashes = 0
        self._turn_durations: list[float] = []
        self._schema(self.database_path)

    @staticmethod
    def _schema(path: Path) -> None:
        from contextlib import closing
        import sqlite3
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS bridge_schema(version INTEGER NOT NULL)")
            row = db.execute("SELECT version FROM bridge_schema LIMIT 1").fetchone()
            if row is None:
                db.execute("INSERT INTO bridge_schema(version) VALUES(1)")
                db.execute("""CREATE TABLE IF NOT EXISTS runtime_servers(instance_id TEXT PRIMARY KEY,pid INTEGER,command_fingerprint TEXT NOT NULL,started_at TEXT NOT NULL,status TEXT NOT NULL,last_error TEXT)""")
                db.execute("""CREATE TABLE IF NOT EXISTS runtime_threads(thread_id TEXT PRIMARY KEY,cwd TEXT NOT NULL,profile TEXT NOT NULL,model TEXT,permissions_json TEXT NOT NULL,config_policy TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,agent_metadata_json TEXT NOT NULL DEFAULT '{}',server_id TEXT)""")
                db.execute("""CREATE TABLE IF NOT EXISTS runtime_turns(turn_id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,model TEXT,error TEXT,final_text TEXT NOT NULL DEFAULT '',bridge_run_id TEXT,agent_metadata_json TEXT NOT NULL DEFAULT '{}')""")
                db.execute("""CREATE TABLE IF NOT EXISTS runtime_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,thread_id TEXT,turn_id TEXT,event_type TEXT NOT NULL,created_at TEXT NOT NULL,payload_json TEXT NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS turn_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,thread_id TEXT,turn_id TEXT,event_type TEXT NOT NULL,timestamp TEXT NOT NULL,payload_json TEXT NOT NULL,bridge_run_id TEXT)""")
            elif row[0] != 1:
                raise RuntimeError(f"unsupported bridge registry schema version: {row[0]}")
            db.execute("""CREATE TABLE IF NOT EXISTS turn_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,thread_id TEXT,turn_id TEXT,event_type TEXT NOT NULL,timestamp TEXT NOT NULL,payload_json TEXT NOT NULL,bridge_run_id TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS runtime_control_requests(request_id TEXT PRIMARY KEY,bridge_run_id TEXT NOT NULL,action TEXT NOT NULL,status TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL)""")
            thread_columns = {r[1] for r in db.execute("PRAGMA table_info(runtime_threads)")}
            if "agent_metadata_json" not in thread_columns: db.execute("ALTER TABLE runtime_threads ADD COLUMN agent_metadata_json TEXT NOT NULL DEFAULT '{}'" )
            if "server_id" not in thread_columns: db.execute("ALTER TABLE runtime_threads ADD COLUMN server_id TEXT")
            turn_columns = {r[1] for r in db.execute("PRAGMA table_info(runtime_turns)")}
            for name, definition in {"bridge_run_id": "TEXT", "agent_metadata_json": "TEXT NOT NULL DEFAULT '{}'"}.items():
                if name not in turn_columns: db.execute(f"ALTER TABLE runtime_turns ADD COLUMN {name} {definition}")

    def _db(self, sql: str, values: tuple[Any, ...] = ()) -> None:
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.database_path, timeout=10)) as db, db: db.execute(sql, values)

    def _spawn_background(self, target, *, name: str) -> None:
        def run() -> None:
            try:
                target()
            finally:
                with self._background_threads_lock:
                    self._background_threads.discard(threading.current_thread())
        thread = threading.Thread(target=run, name=name, daemon=True)
        with self._background_threads_lock:
            self._background_threads.add(thread)
        thread.start()

    def _dispatch_available_backends(self) -> None:
        self.dispatch_scheduled()
        from ._exec_dispatch import dispatch as dispatch_exec
        dispatch_exec(self.database_path)

    def _control_loop(self) -> None:
        from contextlib import closing
        import sqlite3
        while not self._control_stop.wait(0.05):
            try:
                with closing(sqlite3.connect(self.database_path, timeout=2)) as db, db:
                    row = db.execute("SELECT request_id,bridge_run_id,action FROM runtime_control_requests WHERE status='PENDING' ORDER BY created_at LIMIT 1").fetchone()
                    if row:
                        db.execute("UPDATE runtime_control_requests SET status='PROCESSING' WHERE request_id=? AND status='PENDING'", (row[0],))
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                # Runtime events and scheduler claims share this SQLite file.
                # A transient writer lock must not permanently kill the control
                # worker; the pending request remains available for the next poll.
                logger.debug("Runtime control poll deferred by SQLite contention")
                continue
            if not row:
                continue
            request_id, bridge_run_id, action = row
            try:
                if action == "dispatch":
                    self._dispatch_available_backends()
                elif action == "interrupt":
                    run = next((item for item in self.scheduler.list_runs() if item["bridge_run_id"] == bridge_run_id), None)
                    if not run or run["backend"] != "app-server" or run["status"] not in {"RUNNING", "WAITING_APPROVAL"}:
                        raise RuntimeError("app-server run is not active")
                    self.request("turn/interrupt", {"threadId": run["thread_id"], "turnId": run["turn_id"]}, timeout=5)
                else:
                    raise RuntimeError("unsupported runtime control action")
                status, error = "COMPLETED", None
            except Exception as exc:
                status, error = "FAILED", redact(str(exc))[:300]
            while not self._control_stop.is_set():
                try:
                    with closing(sqlite3.connect(self.database_path, timeout=2)) as db, db:
                        db.execute("UPDATE runtime_control_requests SET status=?,error=? WHERE request_id=?", (status, error, request_id))
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                        raise
                    logger.debug("Runtime control result write deferred by SQLite contention")
                    self._control_stop.wait(0.05)

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.process and self.process.poll() is None and self.state == RuntimeState.HEALTHY:
                return self.health()
            self.state = RuntimeState.STARTING
            try:
                self._singleton.acquire()
                self._db("UPDATE runtime_servers SET status='LOST',last_error='previous manager owner is no longer active' WHERE status IN ('STARTING','HEALTHY')")
                kwargs: dict[str, Any] = {}
                if os.name == "nt":
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    kwargs["startupinfo"] = startup
                self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, cwd=str(self.cwd), env=codex_environment(), shell=False, bufsize=0, **kwargs)
                fingerprint = hashlib.sha256(json.dumps(self.command).encode()).hexdigest()
                self._db("INSERT OR REPLACE INTO runtime_servers VALUES(?,?,?,?,?,NULL)", (self.instance_id, self.process.pid, fingerprint, _now(), "STARTING"))
                self._reader_stop.clear()
                self._reader = threading.Thread(target=self._read_loop, name="p4-codex-app-server-reader", daemon=True); self._reader.start()
            except Exception:
                self.state = RuntimeState.CRASHED; self._singleton.release(); raise
        try:
            response = self.request("initialize", {"clientInfo": {"name": "p4-codex-bridge", "title": "P4 Codex Bridge", "version": __version__}}, timeout=self.startup_timeout)
            self.server_info = response.get("serverInfo", {}) if isinstance(response, dict) else {}
            self.protocol_version = str(response.get("protocolVersion", "unknown")) if isinstance(response, dict) else "unknown"
            self.request("initialized", {}, timeout=self.startup_timeout, notification=True)
            self.state = RuntimeState.HEALTHY
            self._control_stop.clear()
            self._control_thread = threading.Thread(target=self._control_loop, name="p4-codex-runtime-control", daemon=True)
            self._control_thread.start()
            self._db("UPDATE runtime_servers SET status='HEALTHY' WHERE instance_id=?", (self.instance_id,))
            self.recover(dry_run=False)
            self._restore_queued()
            self.dispatch_scheduled()
            return self.health()
        except Exception as exc:
            self.state = RuntimeState.CRASHED
            self._db("UPDATE runtime_servers SET status='CRASHED',last_error=? WHERE instance_id=?", (redact(str(exc)), self.instance_id))
            self.stop(mode="FORCE")
            raise

    def _write(self, message: dict[str, Any]) -> None:
        proc = self.process
        if not proc or proc.poll() is not None or not proc.stdin: raise RuntimeError("app-server process is not running")
        payload = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._write_lock: proc.stdin.write(payload); proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 30, notification: bool = False) -> dict[str, Any]:
        if notification:
            self._write({"jsonrpc": "2.0", "method": method, "params": params or {}}); return {}
        with self._lock:
            if len(self._pending) >= self.max_pending_requests: raise RuntimeError("app-server pending request limit reached")
            self._next_id += 1; request_id = self._next_id; response: queue.Queue = queue.Queue(1); self._pending[request_id] = response
        try:
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            try: value = response.get(timeout=timeout)
            except queue.Empty as exc: raise TimeoutError(f"app-server request timed out: {method}") from exc
            if isinstance(value, BaseException): raise value
            if "error" in value: raise RuntimeError(redact(str(value["error"].get("message", "app-server request failed"))))
            return value.get("result", {}) if isinstance(value.get("result"), dict) else {}
        finally:
            with self._lock: self._pending.pop(request_id, None)

    def _read_loop(self) -> None:
        import json
        proc = self.process
        try:
            assert proc and proc.stdout
            for raw in iter(proc.stdout.readline, b""):
                if self._reader_stop.is_set(): break
                try: msg = json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError): self._protocol_errors += 1; continue
                if not isinstance(msg, dict): self._protocol_errors += 1; continue
                if "id" in msg and ("result" in msg or "error" in msg):
                    with self._lock: target = self._pending.get(msg["id"])
                    if target:
                        try: target.put_nowait(msg)
                        except queue.Full: pass
                    continue
                if "method" in msg and "id" in msg:
                    # Approval/server requests are not wired into this manager yet.
                    # Fail closed instead of leaving the turn blocked or approving.
                    self._protocol_errors += 1
                    self._write({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "runtime manager does not expose approval handling"}})
                    params = msg.get("params", {}) if isinstance(msg.get("params"), dict) else {}
                    event = {"type": "ServerError", "thread_id": params.get("threadId"), "turn_id": params.get("turnId"), "timestamp": _now(),
                             "data": {"code": "APPROVAL_NOT_EXPOSED", "method": msg.get("method")}}
                    self._db("INSERT INTO runtime_events(thread_id,turn_id,event_type,created_at,payload_json) VALUES(?,?,?,?,?)", (event["thread_id"], event["turn_id"], event["type"], event["timestamp"], json.dumps(event)))
                    continue
                if "method" in msg and "id" not in msg: self._event(msg)
        except (OSError, ValueError): self._protocol_errors += 1
        finally:
            self._fail_pending()
            if not self._reader_stop.is_set():
                self._crashes += 1; self.state = RuntimeState.CRASHED
                self._db("UPDATE runtime_servers SET status='CRASHED',last_error='app-server stream closed' WHERE instance_id=?", (self.instance_id,))
                for turn in list(self.turns.values()):
                    if turn.status in {TurnState.RUNNING, TurnState.WAITING_APPROVAL}:
                        self._transition(turn, TurnState.UNKNOWN, error="app-server disconnected; remote outcome unknown")

    def _fail_pending(self) -> None:
        with self._lock: waiting = tuple(self._pending.values())
        for target in waiting:
            try: target.put_nowait(RuntimeError("app-server connection closed"))
            except queue.Full: pass

    def _event(self, message: dict[str, Any]) -> None:
        self._received += 1; method = message.get("method"); p = message.get("params", {})
        if not isinstance(p, dict): p = {}
        tid, turnid = p.get("threadId"), p.get("turnId")
        typ = {"thread/started": "ThreadStarted", "turn/started": "TurnStarted", "turn/completed": "TurnCompleted", "thread/tokenUsage/updated": "TokenUsageUpdated", "item/agentMessage/delta": "AgentMessageDelta"}.get(method, str(method))
        item = p.get("item") if isinstance(p.get("item"), dict) else {}
        if method == "item/started": typ = "ToolStarted" if is_tool_item(item) else "ItemStarted"
        elif method == "item/completed":
            typ = "ToolCompleted" if is_tool_item(item) else "AgentMessageCompleted" if item.get("type") == "agentMessage" else "ItemCompleted"
        turn = self.turns.get(turnid) if turnid else None
        if turn is None and tid:
            turn = next((item for item in self.turns.values() if item.thread_id == tid and item.status in {TurnState.CREATED, TurnState.QUEUED, TurnState.RUNNING, TurnState.WAITING_APPROVAL}), None)
            if turn is not None and turnid:
                self._rekey_turn(turn, str(turnid))
            elif turn is not None:
                # Some installed app-server notifications identify the active
                # turn only by threadId. Associate them with the bridge's
                # current turn so watch/replay can retrieve lifecycle events.
                turnid = turn.turn_id
        if turn:
            if typ == "TurnStarted" and turn.status in {TurnState.CREATED, TurnState.QUEUED}: self._transition(turn, TurnState.RUNNING)
            elif typ == "TurnCompleted":
                status = str(p.get("turn", {}).get("status", "completed")).lower()
                final = TurnState.INTERRUPTED if status == "interrupted" else TurnState.FAILED if status == "failed" else TurnState.COMPLETED
                if turn.status not in {TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED}: self._transition(turn, final)
                turn.finished_at = _now()
                if final == TurnState.COMPLETED: self._completed += 1
                else: self._failed += int(final == TurnState.FAILED)
                self.scheduler.finish(turn.bridge_run_id, final.value, finished_at=turn.finished_at, error=turn.error)
                self._queued = len(self.scheduler.resources()["queued_runs"])
                self._spawn_background(self._dispatch_available_backends, name="p4-codex-scheduler-dispatch")
                self._emit_scheduling_event(turn, "RESOURCE_RELEASED", {})
                if turn.announce_run:
                    logger.info("[P4-Codex] %s %s | %s", "Completed" if final == TurnState.COMPLETED else "Failed", turn.bridge_run_id, final.value)
            elif typ == "AgentMessageDelta": turn.final_text += str(p.get("delta", ""))
            elif method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/permissions/requestApproval"}:
                if turn.status == TurnState.RUNNING:
                    self._transition(turn, TurnState.WAITING_APPROVAL)
                    self.scheduler.set_status(turn.bridge_run_id, "WAITING_APPROVAL")
        event = {"type": typ, "thread_id": tid, "turn_id": turnid, "timestamp": _now(), "data": p}
        if turn: turn.events.append(event)
        if typ in {"ThreadStarted", "TurnStarted", "TurnCompleted", "TokenUsageUpdated", "ServerError", "AgentMessageDelta", "ToolStarted", "ToolCompleted"}:
            safe_event = redact_structured(event)
            encoded = json.dumps(safe_event, ensure_ascii=False)
            if len(encoded.encode("utf-8")) > 64 * 1024:
                encoded = json.dumps({"type": typ, "timestamp": event["timestamp"], "truncated": True})
            self._db("INSERT INTO runtime_events(thread_id,turn_id,event_type,created_at,payload_json) VALUES(?,?,?,?,?)", (tid, turnid, typ, event["timestamp"], encoded))

    def create_thread(self, *, cwd: str | Path | None = None, profile: str = "analysis", model: str | None = None,
                      sandbox: str = "read-only", approval_policy: str = "never", config_policy: str = "project",
                      metadata: dict[str, Any] | None = None) -> ManagedThread:
        if self.state != RuntimeState.HEALTHY: raise RuntimeError("runtime manager is not healthy")
        if len(self.threads) >= self.max_threads: raise RuntimeError("max_threads limit reached")
        root = Path(cwd or self.cwd).expanduser().resolve(strict=True)
        if not root.is_dir(): raise ValueError("cwd must be a directory")
        result = self.request("thread/start", {"cwd": str(root), "model": model, "sandbox": sandbox, "approvalPolicy": approval_policy, "ephemeral": False})
        thread_id = result.get("thread", {}).get("id") or result.get("threadId")
        if not isinstance(thread_id, str) or not thread_id: raise RuntimeError("app-server thread/start returned no id")
        from .registry import _clean_metadata
        metadata = _clean_metadata(metadata or {})
        thread = ManagedThread(thread_id, str(root), profile, model, {"sandbox": sandbox, "approval_policy": approval_policy}, config_policy, agent_metadata=metadata, server_id=self.instance_id)
        self.threads[thread_id] = thread
        self._db("INSERT OR REPLACE INTO runtime_threads(thread_id,cwd,profile,model,permissions_json,config_policy,created_at,updated_at,status,agent_metadata_json,server_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (thread.thread_id, thread.cwd, profile, model, json.dumps(thread.permissions), config_policy, thread.created_at, thread.updated_at, thread.status, json.dumps(metadata, ensure_ascii=False), self.instance_id))
        return thread

    def start_turn(self, thread_id: str, prompt: str, *, timeout: float = 300, metadata: dict[str, Any] | None = None,
                   announce_run: bool = False, access_mode: str = "READ", resource_priority: int = 0) -> ManagedTurn:
        if thread_id not in self.threads: raise KeyError("unknown bridge-managed thread")
        if not isinstance(prompt, str) or not prompt.strip(): raise ValueError("prompt is required")
        if len(self.scheduler.resources(self.runtime_limits)["queued_runs"]) >= self.max_pending_requests: raise RuntimeError("QUEUE_LIMIT: pending turn limit reached")
        thread = self.threads[thread_id]
        from .registry import _clean_metadata
        merged_metadata = {**thread.agent_metadata, **_clean_metadata(metadata or {})}
        bridge_run_id = "br_" + uuid.uuid4().hex[:12]
        if not isinstance(announce_run, bool): raise ValueError("announce_run must be boolean")
        turn = ManagedTurn(str(uuid.uuid4()), thread_id, TurnState.SUBMITTED, _now(), thread.model, bridge_run_id=bridge_run_id, agent_metadata=merged_metadata, announce_run=announce_run)
        self.turns[turn.turn_id] = turn
        from .scheduler import canonical_workspace
        workspace = canonical_workspace(thread.cwd)
        def record_turn(db, _run_id):
            db.execute("INSERT INTO runtime_turns(turn_id,thread_id,status,started_at,model,final_text,bridge_run_id,agent_metadata_json) VALUES(?,?,?,?,?,?,?,?)", (turn.turn_id, thread_id, turn.status.value, turn.started_at, thread.model, "", bridge_run_id, json.dumps(merged_metadata, ensure_ascii=False)))
        self.scheduler.submit(turn_id=turn.turn_id, thread_id=thread_id, backend="app-server", profile=thread.profile,
                              workspace=workspace, prompt=prompt, access_mode=access_mode, priority=resource_priority,
                              metadata=merged_metadata, bridge_run_id=bridge_run_id, submitted_at=turn.started_at, transaction_hook=record_turn,
                              queue_limit=self.max_pending_requests)
        self._emit_scheduling_event(turn, "SUBMITTED", {})
        self._transition(turn, TurnState.QUEUED)
        self._emit_scheduling_event(turn, "QUEUED", {})
        if announce_run:
            logger.info("[P4-Codex] Started %s\n[P4-Codex] Agent: %s\n[P4-Codex] Task: %s\n[P4-Codex] Backend: app-server\n[P4-Codex] Thread: %s\n[P4-Codex] PID: %s\n[P4-Codex] Watch: p4-codex watch %s --follow",
                        bridge_run_id, merged_metadata.get("agent_name", "-"), merged_metadata.get("task_key", "-"), thread_id,
                        self.process.pid if self.process else "-", bridge_run_id)
        self.dispatch_scheduled(timeout=timeout)
        scheduled = self.scheduler.get(bridge_run_id)
        if scheduled and scheduled["status"] == "WAITING_FOR_SLOT":
            self._transition(turn, TurnState.WAITING_FOR_SLOT)
            details = {"waiting_reason": scheduled["waiting_reason"], "blocked_by_run_id": scheduled["blocked_by_run_id"], "queue_position": scheduled["queue_position"]}
            self._emit_scheduling_event(turn, "WAITING_FOR_SLOT", details)
            self._emit_scheduling_event(turn, "RESOURCE_BLOCKED", details)
        self._queued = len(self.scheduler.resources()["queued_runs"])
        return turn

    def dispatch_scheduled(self, *, timeout: float = 300) -> list[str]:
        claimed = self.scheduler.dispatch(limits=self.runtime_limits, backend="app-server")
        dispatched: list[str] = []
        failed_claim = False
        for item in claimed:
            turn = self.turns.get(item["turn_id"])
            if turn is None:
                # Recovery never replays a claim whose outcome is unknown.
                self.scheduler.finish(item["bridge_run_id"], "LOST", finished_at=_now(), error="claimed turn is not present in this manager")
                continue
            self._active += 1
            self._max_observed_concurrency = max(self._max_observed_concurrency, self._active)
            if turn.status in {TurnState.QUEUED, TurnState.WAITING_FOR_SLOT}: self._transition(turn, TurnState.RUNNING)
            self._emit_scheduling_event(turn, "RUNNING", {})
            self._emit_scheduling_event(turn, "RESOURCE_ACQUIRED", {"workspace": item["workspace"], "access_mode": item["access_mode"]})
            try:
                payload = item["payload"]
                result = self.request("turn/start", {"threadId": item["thread_id"], "input": [{"type": "text", "text": payload["prompt"]}], "cwd": item["workspace"], "model": turn.model}, timeout=timeout)
                authoritative = result.get("turn", {}).get("id")
                if isinstance(authoritative, str) and authoritative:
                    self._rekey_turn(turn, authoritative)
                    self.scheduler.rekey_turn(turn.bridge_run_id, authoritative)
                dispatched.append(turn.bridge_run_id)
            except Exception as exc:
                failed_claim = True
                self._transition(turn, TurnState.FAILED, error=redact(str(exc)))
                self.scheduler.finish(turn.bridge_run_id, "FAILED", finished_at=_now(), error=redact(str(exc)))
                self._emit_scheduling_event(turn, "FAILED", {"error": redact(str(exc))})
        self._queued = len(self.scheduler.resources()["queued_runs"])
        if failed_claim:
            self._spawn_background(self.dispatch_scheduled, name="p4-codex-scheduler-retry")
        return dispatched

    def _restore_queued(self) -> None:
        """Rehydrate only unclaimed queue work; claimed remote turns stay LOST."""
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.database_path)) as db:
            db.row_factory = sqlite3.Row
            threads = db.execute("SELECT * FROM runtime_threads").fetchall()
            rows = db.execute("""SELECT t.* FROM runtime_turns t JOIN scheduler_runs q ON q.bridge_run_id=t.bridge_run_id
                WHERE q.status IN ('QUEUED','WAITING_FOR_SLOT') ORDER BY q.priority DESC,q.submitted_at,q.bridge_run_id""").fetchall()
        for row in threads:
            if row["thread_id"] in self.threads: continue
            self.threads[row["thread_id"]] = ManagedThread(row["thread_id"], row["cwd"], row["profile"], row["model"],
                json.loads(row["permissions_json"] or "{}"), row["config_policy"], row["created_at"], row["updated_at"], row["status"],
                json.loads(row["agent_metadata_json"] or "{}"), row["server_id"] or "")
        for row in rows:
            restored_status = TurnState.QUEUED if row["status"] == TurnState.SUBMITTED.value else TurnState(row["status"])
            turn = ManagedTurn(row["turn_id"], row["thread_id"], restored_status, row["started_at"], row["model"],
                bridge_run_id=row["bridge_run_id"], agent_metadata=json.loads(row["agent_metadata_json"] or "{}"))
            self.turns[turn.turn_id] = turn
            if row["status"] == TurnState.SUBMITTED.value:
                self._db("UPDATE runtime_turns SET status='QUEUED' WHERE turn_id=?", (turn.turn_id,))

    def _emit_scheduling_event(self, turn: ManagedTurn, kind: str, data: dict[str, Any]) -> None:
        event = {"type": kind, "thread_id": turn.thread_id, "turn_id": turn.turn_id, "timestamp": _now(), "data": data}
        turn.events.append(event)
        self._db("INSERT INTO runtime_events(thread_id,turn_id,event_type,created_at,payload_json) VALUES(?,?,?,?,?)", (turn.thread_id, turn.turn_id, kind, event["timestamp"], json.dumps(redact_structured(event), ensure_ascii=False)))
        self._db("INSERT INTO turn_events(thread_id,turn_id,event_type,timestamp,payload_json,bridge_run_id) VALUES(?,?,?,?,?,?)", (turn.thread_id, turn.turn_id, kind, event["timestamp"], json.dumps(redact_structured(event), ensure_ascii=False), turn.bridge_run_id))

    def cancel(self, run_id: str) -> bool:
        row = next((item for item in self.scheduler.list_runs() if item["bridge_run_id"] == run_id or item["turn_id"] == run_id), None)
        if row is None: raise KeyError(run_id)
        if row["status"] in {"QUEUED", "WAITING_FOR_SLOT"}:
            cancelled = self.scheduler.cancel(row["bridge_run_id"], finished_at=_now())
            turn = self.turns.get(row["turn_id"])
            if turn and cancelled:
                self._transition(turn, TurnState.CANCELLED)
                self._emit_scheduling_event(turn, "CANCELLED", {})
            self.dispatch_scheduled()
            return cancelled
        if row["status"] == "RUNNING":
            self.request("turn/interrupt", {"threadId": row["thread_id"], "turnId": row["turn_id"]}, timeout=5)
            return True
        return False

    def get_resource_status(self) -> dict[str, Any]: return self.scheduler.resources(self.runtime_limits)

    def get_runtime_limits(self): return self.runtime_limits

    def set_runtime_limits(self, limits) -> None:
        from .scheduler import RuntimeLimits
        if not isinstance(limits, RuntimeLimits): raise TypeError("limits must be RuntimeLimits")
        self.runtime_limits = limits
        self.scheduler.limits = limits
        self.scheduler.persist_limits(limits)
        self.dispatch_scheduled()

    def list_runs(self, *, active: bool = False) -> list[dict[str, Any]]:
        return self.scheduler.list_runs(active=active)

    def inspect(self, run_id: str) -> dict[str, Any]:
        row = self.scheduler.get(run_id)
        if row is None: raise KeyError(run_id)
        return {key: row.get(key) for key in ("bridge_run_id", "turn_id", "thread_id", "backend", "profile", "workspace", "access_mode", "status", "submitted_at", "started_at", "finished_at", "waiting_reason", "blocked_by_run_id", "queue_position", "error")}

    def _transition(self, turn: ManagedTurn, status: TurnState, *, error: str | None = None) -> None:
        status = TurnState(status)
        if status == turn.status: return
        if status not in _TRANSITIONS.get(turn.status, set()): raise ValueError(f"invalid turn transition {turn.status} -> {status}")
        was_active = turn.status in {TurnState.RUNNING, TurnState.WAITING_APPROVAL}
        turn.status = status; turn.error = redact(error) if error else turn.error
        if status in {TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED, TurnState.LOST, TurnState.UNKNOWN, TurnState.CANCELLED}:
            turn.finished_at = turn.finished_at or _now()
            if was_active: self._active = max(0, self._active - 1)
        self._db("UPDATE runtime_turns SET status=?,finished_at=?,error=?,final_text=? WHERE turn_id=?", (status.value, turn.finished_at, turn.error, turn.final_text, turn.turn_id))
        if status in {TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED, TurnState.LOST, TurnState.UNKNOWN, TurnState.CANCELLED} and turn.bridge_run_id:
            scheduler_row = self.scheduler.get(turn.bridge_run_id)
            if scheduler_row and scheduler_row["status"] not in {"COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED", "LOST"}:
                terminal = "LOST" if status == TurnState.UNKNOWN else status.value
                self.scheduler.finish(turn.bridge_run_id, terminal, finished_at=turn.finished_at or _now(), error=turn.error)

    def _rekey_turn(self, turn: ManagedTurn, turn_id: str) -> None:
        old_id = turn.turn_id
        if old_id == turn_id: return
        self.turns.pop(old_id, None); turn.turn_id = turn_id; self.turns[turn_id] = turn
        for event in turn.events:
            if event.get("turn_id") == old_id:
                event["turn_id"] = turn_id
        self._db("UPDATE runtime_turns SET turn_id=? WHERE turn_id=?", (turn_id, old_id))
        self._db("UPDATE runtime_events SET turn_id=? WHERE turn_id=?", (turn_id, old_id))
        self._db("UPDATE turn_events SET turn_id=? WHERE turn_id=?", (turn_id, old_id))

    def get_turn(self, turn_id: str) -> ManagedTurn | None: return self.turns.get(turn_id)
    def list_threads(self) -> list[dict[str, Any]]: return [vars(x).copy() for x in self.threads.values()]
    def list_turns(self) -> list[dict[str, Any]]: return [{**vars(x), "status": x.status.value, "events": len(x.events)} for x in self.turns.values()]

    def recover(self, *, dry_run: bool = True) -> dict[str, Any]:
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.database_path)) as db, db:
            rows = db.execute("SELECT turn_id,thread_id,status FROM runtime_turns WHERE status IN ('RUNNING','WAITING_APPROVAL')").fetchall()
        actions = [{"turn_id": tid, "thread_id": thid, "previous": status, "classification": "UNKNOWN", "action": "mark UNKNOWN; never re-execute automatically"} for tid, thid, status in rows]
        if not dry_run:
            with closing(sqlite3.connect(self.database_path)) as db, db:
                db.executemany("UPDATE runtime_turns SET status='UNKNOWN',error='bridge restarted; outcome requires reconciliation' WHERE turn_id=?", [(x[0],) for x in rows])
            self.scheduler.reconcile_after_restart(finished_at=_now(), backend="app-server")
        return {"dry_run": dry_run, "actions": actions}

    def get_metrics(self) -> dict[str, Any]:
        resources = self.scheduler.resources(self.runtime_limits)
        queue_rows = resources["queued_runs"]
        wait_ms = []
        from datetime import datetime, timezone
        for row in self.scheduler.list_runs():
            try:
                if row["started_at"]: wait_ms.append(max(0, int((datetime.fromisoformat(row["started_at"]) - datetime.fromisoformat(row["submitted_at"])).total_seconds() * 1000)))
            except (TypeError, ValueError): pass
        return {"server_uptime_seconds": None, "active_threads": len(self.threads), "active_turns": self._active, "queued_turns": len(queue_rows),
                "queue_length": len(queue_rows), "queued_total": len(self.scheduler.list_runs()), "waiting_for_slot": sum(x["status"] == "WAITING_FOR_SLOT" for x in queue_rows),
                "active_slots": resources["global"]["used"], "free_slots": resources["global"]["free"], "workspace_locks": len(resources["workspace_locks"]),
                "dispatch_total": sum(1 for x in self.scheduler.list_runs() if x["started_at"]), "cancelled_before_start": sum(x["status"] == "CANCELLED" for x in self.scheduler.list_runs()),
                "queue_wait_ms_avg": sum(wait_ms)//len(wait_ms) if wait_ms else 0, "queue_wait_ms_max": max(wait_ms, default=0), "max_observed_concurrency": self._max_observed_concurrency,
                "waiting_approvals": sum(t.status == TurnState.WAITING_APPROVAL for t in self.turns.values()), "completed_turns": sum(t.status == TurnState.COMPLETED for t in self.turns.values()),
                "failed_turns": sum(t.status == TurnState.FAILED for t in self.turns.values()), "interrupted_turns": sum(t.status == TurnState.INTERRUPTED for t in self.turns.values()),
                "server_restarts": self._restarts, "crashes": self._crashes, "protocol_errors": self._protocol_errors, "events_received": self._received,
                "events_dropped": 0, "average_turn_duration_seconds": None, "token_usage": None}

    def health(self) -> dict[str, Any]:
        alive = bool(self.process and self.process.poll() is None)
        db_ok = True
        try:
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(self.database_path, timeout=0.2)) as db, db: db.execute("SELECT 1")
        except Exception: db_ok = False
        status = self.state.value if alive and db_ok else "DEGRADED" if alive else self.state.value
        return {"status": status, "server": {"alive": alive, "pid": self.process.pid if alive and self.process else None, "protocol_version": self.protocol_version, "server_info": self.server_info},
                "registry": {"accessible": db_ok}, "threads": {"count": len(self.threads)}, "turns": {"active": self._active, "queued": self._queued},
                "queue": self.scheduler.resources(self.runtime_limits), "limits": self.runtime_limits.__dict__, "compatibility": self.get_capabilities()}

    def get_capabilities(self) -> dict[str, Any]:
        return {"bridge_can_support": ["app_server.multiple_threads", "app_server.multiple_turns", "runtime.health", "runtime.recovery"],
                "codex_supports": {"app_server": bool(self.protocol_version), "thread_resume": "not_probed"},
                "effective_available": self.state == RuntimeState.HEALTHY, "protocol_version": self.protocol_version, "cli_version": None, "bridge_version": __version__}

    def restart(self) -> dict[str, Any]:
        self.stop(mode="WAIT"); self._restarts += 1; return self.start()

    def stop(self, *, mode: str = "WAIT", timeout: float = 5) -> None:
        if mode not in {"WAIT", "INTERRUPT", "FORCE"}: raise ValueError("mode must be WAIT, INTERRUPT or FORCE")
        crashed = self.state == RuntimeState.CRASHED
        self.state = RuntimeState.STOPPING
        if mode == "INTERRUPT":
            for t in list(self.turns.values()):
                if t.status == TurnState.RUNNING:
                    try: self.request("turn/interrupt", {"threadId": t.thread_id, "turnId": t.turn_id}, timeout=min(timeout, 2))
                    except Exception: pass
        proc = self.process
        self._control_stop.set()
        self._reader_stop.set()
        if proc and proc.poll() is None:
            try:
                if proc.stdin: proc.stdin.close()
                proc.wait(timeout=0.2 if mode == "FORCE" else timeout)
            except (OSError, subprocess.TimeoutExpired):
                # The process is our direct child; do not discover/kill by PID alone.
                try: proc.terminate(); proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    try: proc.kill(); proc.wait(timeout=2)
                    except OSError: pass
        if self._reader and threading.current_thread() is not self._reader: self._reader.join(timeout=1)
        if self._control_thread and threading.current_thread() is not self._control_thread:
            self._control_thread.join(timeout=max(1, timeout))
        with self._background_threads_lock:
            background_threads = tuple(self._background_threads)
        for thread in background_threads:
            if thread is not threading.current_thread(): thread.join(timeout=max(1, timeout))
        self._fail_pending(); self._singleton.release()
        if proc:
            for stream in (proc.stdin, proc.stdout):
                if stream:
                    try: stream.close()
                    except OSError: pass
        self.state = RuntimeState.CRASHED if crashed else RuntimeState.STOPPED
        if self.process:
            self._db("UPDATE runtime_servers SET status=? WHERE instance_id=?", (self.state.value, self.instance_id))
        self.process = None

    close = stop

    def __enter__(self) -> "CodexRuntimeManager": self.start(); return self
    def __exit__(self, *_: object) -> None: self.stop()
