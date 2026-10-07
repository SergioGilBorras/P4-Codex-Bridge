"""Foreground resident service and same-machine SQLite control channel."""
from __future__ import annotations

import json
import hashlib
import logging
import logging.handlers
import os
import signal
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .runtime import codex_environment, probe, redact, resolve_codex_command
from .scheduler import RuntimeLimits
from .errors import ServiceUnavailableError


SERVICE_STATES = {"STARTING", "RECOVERING", "HEALTHY", "DEGRADED", "STOPPING", "STOPPED", "CRASHED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state_dir() -> Path:
    configured = os.environ.get("P4_CODEX_BRIDGE_STATE_DIR")
    if configured:
        return Path(os.path.expandvars(configured)).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) if os.name == "nt" else Path.home() / ".local" / "state"
    return (base / "p4-codex-bridge").resolve()


@dataclass(frozen=True)
class ServiceConfig:
    state_dir: Path
    cwd: Path
    log_dir: Path
    runtime_limits: RuntimeLimits = field(default_factory=RuntimeLimits)
    startup_timeout_seconds: float = 20
    shutdown_timeout_seconds: float = 30
    shutdown_policy: str = "WAIT"
    approval_timeout_seconds: float = 300
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 4
    codex_executable: str | None = None
    allowed_roots: tuple[Path, ...] = ()
    structured_logs: bool = False
    retention_days: int = 30
    max_completed_runs: int = 1000
    max_events_per_run: int = 2000

    @classmethod
    def load(cls, path: str | Path | None = None, *, state_dir: str | Path | None = None) -> "ServiceConfig":
        raw: dict[str, Any] = {}
        selected = Path(os.path.expandvars(str(path))).expanduser().resolve() if path else None
        if selected and selected.is_file():
            try:
                try:
                    import tomllib
                except ImportError:  # Python 3.10
                    import tomli as tomllib  # type: ignore[no-redef]
                content = selected.read_bytes()
                if content.startswith(b"\xef\xbb\xbf"):
                    content = content[3:]
                raw = tomllib.loads(content.decode("utf-8"))
            except Exception as exc:
                raise ValueError(f"invalid service TOML configuration ({type(exc).__name__})") from exc
        elif selected:
            raise ValueError("service config file does not exist")
        allowed_sections = {"service", "runtime", "logging", "codex", "retention"}
        if not isinstance(raw, dict) or set(raw) - allowed_sections:
            raise ValueError("service config contains an unknown top-level section")
        for section in raw.values():
            if not isinstance(section, dict):
                raise ValueError("service config sections must be tables")
        service = raw.get("service", {})
        runtime = raw.get("runtime", {})
        logging_cfg = raw.get("logging", {})
        codex = raw.get("codex", {})
        retention = raw.get("retention", {})
        allowed = {
            "service": {"state_dir", "cwd", "startup_timeout_seconds", "shutdown_timeout_seconds", "shutdown_policy", "approval_timeout_seconds"},
            "runtime": {"global_max_active", "app_server_max_active", "exec_max_active", "max_active_threads", "max_queue_size", "profile_limits"},
            "logging": {"log_dir", "max_bytes", "backup_count", "format"},
            "codex": {"executable", "allowed_roots"}, "retention": {"days", "max_completed_runs", "max_events_per_run"},
        }
        for name, section in (("service", service), ("runtime", runtime), ("logging", logging_cfg), ("codex", codex), ("retention", retention)):
            if set(section) - allowed[name]:
                raise ValueError(f"unknown keys in [{name}] configuration")
        configured_roots = codex.get("allowed_roots", [str(service.get("cwd") or Path.home())])
        if not isinstance(configured_roots, list) or not configured_roots or any(not isinstance(item, str) for item in configured_roots):
            raise ValueError("codex.allowed_roots must be a nonempty array of absolute directory paths")
        root_paths = [Path(os.path.expandvars(item)).expanduser() for item in configured_roots]
        if any(not item.is_absolute() for item in root_paths):
            raise ValueError("codex.allowed_roots must be absolute paths")
        resolved_roots = tuple(item.resolve(strict=True) for item in root_paths)
        if len({str(item).casefold() for item in resolved_roots}) != len(resolved_roots):
            raise ValueError("codex.allowed_roots must not contain duplicates")
        env_state = os.environ.get("P4_CODEX_BRIDGE_STATE_DIR")
        selected_state = state_dir or env_state or service.get("state_dir") or default_state_dir()
        state_path = Path(os.path.expandvars(str(selected_state))).expanduser()
        if not state_path.is_absolute(): raise ValueError("service state_dir must be absolute")
        root = state_path.resolve()
        cwd_path = Path(os.path.expandvars(str(service.get("cwd") or Path.home()))).expanduser()
        if not cwd_path.is_absolute(): raise ValueError("service cwd must be absolute")
        cwd = cwd_path.resolve(strict=True)
        if not cwd.is_dir():
            raise ValueError("service cwd must be an existing directory")
        log_path = Path(os.path.expandvars(str(logging_cfg.get("log_dir") or (root / "logs")))).expanduser()
        if not log_path.is_absolute(): raise ValueError("logging.log_dir must be absolute")
        log_dir = log_path.resolve()
        limits_values = {key: runtime[key] for key in allowed["runtime"] if key in runtime}
        limits = RuntimeLimits(**limits_values)
        cfg = cls(
            state_dir=root, cwd=cwd, log_dir=log_dir, runtime_limits=limits,
            startup_timeout_seconds=_positive_number(service.get("startup_timeout_seconds", 20), "startup_timeout_seconds"),
            shutdown_timeout_seconds=_positive_number(service.get("shutdown_timeout_seconds", 30), "shutdown_timeout_seconds"),
            shutdown_policy=str(service.get("shutdown_policy", "WAIT")).upper(),
            approval_timeout_seconds=_positive_number(service.get("approval_timeout_seconds", 300), "approval_timeout_seconds"),
            log_max_bytes=_positive_int(logging_cfg.get("max_bytes", 5 * 1024 * 1024), "max_bytes"),
            log_backup_count=_nonnegative_int(logging_cfg.get("backup_count", 4), "backup_count"),
            codex_executable=os.path.expandvars(str(codex["executable"])) if codex.get("executable") else None,
            allowed_roots=resolved_roots,
            structured_logs=logging_cfg.get("format", "human") == "json",
            retention_days=_nonnegative_int(retention.get("days", 30), "retention.days"),
            max_completed_runs=_nonnegative_int(retention.get("max_completed_runs", 1000), "retention.max_completed_runs"),
            max_events_per_run=_nonnegative_int(retention.get("max_events_per_run", 2000), "retention.max_events_per_run"),
        )
        if cfg.shutdown_policy not in {"WAIT", "INTERRUPT", "FORCE"}:
            raise ValueError("shutdown_policy must be WAIT, INTERRUPT or FORCE")
        if logging_cfg.get("format", "human") not in {"human", "json"}:
            raise ValueError("logging.format must be human or json")
        if cfg.codex_executable and ("\x00" in cfg.codex_executable or len(cfg.codex_executable) > 2048):
            raise ValueError("codex.executable is invalid")
        if any(not path.is_dir() for path in cfg.allowed_roots):
            raise ValueError("codex.allowed_roots must contain existing directories")
        if cfg.codex_executable and Path(cfg.codex_executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
            raise ValueError("codex.executable must be a native executable; shell shims are not launched")
        if cfg.startup_timeout_seconds > 600 or cfg.shutdown_timeout_seconds > 3600 or cfg.approval_timeout_seconds > 86400:
            raise ValueError("service timeouts exceed their supported maximum")
        if cfg.log_max_bytes > 1024 * 1024 * 1024 or cfg.log_backup_count > 100 or cfg.retention_days > 3650 or cfg.max_completed_runs > 1_000_000 or cfg.max_events_per_run > 1_000_000:
            raise ValueError("logging/retention values exceed their supported maximum")
        return cfg

    def sanitized(self) -> dict[str, Any]:
        return {
            "state_dir": str(self.state_dir), "cwd": str(self.cwd), "log_dir": str(self.log_dir),
            "runtime_limits": asdict(self.runtime_limits), "startup_timeout_seconds": self.startup_timeout_seconds,
            "shutdown_timeout_seconds": self.shutdown_timeout_seconds, "shutdown_policy": self.shutdown_policy,
            "approval_timeout_seconds": self.approval_timeout_seconds, "log_max_bytes": self.log_max_bytes,
            "log_backup_count": self.log_backup_count, "codex_executable": self.codex_executable,
            "structured_logs": self.structured_logs, "retention_days": self.retention_days,
            "max_completed_runs": self.max_completed_runs, "max_events_per_run": self.max_events_per_run,
            "allowed_roots": [str(path) for path in self.allowed_roots],
        }


def _positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return float(value)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


@contextmanager
def _connect(db_path: Path):
    db = sqlite3.connect(db_path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_service_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as db:
        # Keep service/control schema changes atomic with their additive ALTERs.
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS bridge_service_state(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), instance_id TEXT NOT NULL,
            pid INTEGER NOT NULL, process_identity TEXT, state TEXT NOT NULL, started_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL, payload_json TEXT NOT NULL, last_fatal_error TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bridge_service_commands(
            request_id TEXT PRIMARY KEY, action TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, completed_at TEXT, error TEXT, result_json TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bridge_service_snapshots(
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
            codex_version TEXT, protocol_version TEXT, capability_json TEXT NOT NULL,
            capability_fingerprint TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS bridge_runtime_commands(
            command_id TEXT PRIMARY KEY, command_type TEXT NOT NULL, submitted_at TEXT NOT NULL,
            submitted_by TEXT NOT NULL, payload TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
            payload_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, claimed_by TEXT, claimed_at TEXT, completed_at TEXT,
            result TEXT, error TEXT)""")
        command_columns = {row[1] for row in db.execute("PRAGMA table_info(bridge_runtime_commands)")}
        if "payload_hash" not in command_columns:
            db.execute("ALTER TABLE bridge_runtime_commands ADD COLUMN payload_hash TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_runtime_commands_status_time ON bridge_runtime_commands(status,submitted_at)")
        columns = {row[1] for row in db.execute("PRAGMA table_info(bridge_service_commands)")}
        if "result_json" not in columns:
            db.execute("ALTER TABLE bridge_service_commands ADD COLUMN result_json TEXT")


def read_service_state(state_dir: str | Path) -> dict[str, Any]:
    db_path = Path(state_dir) / "runs.sqlite3"
    if not db_path.exists():
        return {"state": "STOPPED", "running": False, "reason": "state database is absent"}
    try:
        with _connect(db_path) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bridge_service_state'").fetchone()
            row = db.execute("SELECT * FROM bridge_service_state WHERE singleton=1").fetchone() if exists else None
            if not row:
                return {"state": "STOPPED", "running": False, "reason": "service has not registered"}
            data = json.loads(row["payload_json"])
            data.update({"instance_id": row["instance_id"], "pid": row["pid"], "state": row["state"],
                         "started_at": row["started_at"], "heartbeat_at": row["heartbeat_at"],
                         "process_identity": row["process_identity"],
                         "last_fatal_error": row["last_fatal_error"]})
        observed_identity = _process_identity(data.get("pid")) if data.get("pid") else None
        identity = data.get("process_identity")
        identity_verified = bool(identity and observed_identity and identity == observed_identity)
        try:
            heartbeat_age = (datetime.now(timezone.utc) - datetime.fromisoformat(data["heartbeat_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            heartbeat_age = float("inf")
        # A fresh heartbeat is useful liveness evidence only when Windows denied
        # process-time inspection; an explicit identity mismatch never falls back.
        identity_unavailable = not identity or not observed_identity
        alive = identity_verified or (identity_unavailable and 0 <= heartbeat_age <= 5)
        data["process_identity_verified"] = identity_verified
        data["liveness_source"] = "process_identity" if identity_verified else "recent_heartbeat" if alive else "stale_or_mismatched"
        data["running"] = alive
        if not alive and data.get("state") not in {"STOPPED", "CRASHED"}:
            data["state"] = "CRASHED"
        return data
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return {"state": "DEGRADED", "running": False, "reason": "service state is unavailable or invalid"}


def _process_identity(pid: int) -> str | None:
    if os.name != "nt":
        try:
            return str(Path(f"/proc/{pid}/stat").read_text().split()[21])
        except (OSError, IndexError):
            return None
    try:
        import subprocess
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
            f"(Get-Process -Id {int(pid)} -ErrorAction Stop).StartTime.ToUniversalTime().Ticks"],
            capture_output=True, text=True, timeout=3, shell=False)
        value = result.stdout.strip()
        return value if result.returncode == 0 and value.isdigit() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _process_identity_alive(pid: int | None, identity: str | None) -> bool:
    if not pid or not identity:
        return False
    current = _process_identity(int(pid))
    return current is not None and current == identity


def service_snapshot(config: ServiceConfig, manager: Any, instance_id: str, started_at: str,
                     codex_version: str | None,
                     service_state: str, last_fatal_error: str | None = None) -> dict[str, Any]:
    health = manager.health()
    metrics = manager.get_metrics()
    all_runs = manager.scheduler.list_runs()
    queue = health.get("queue", {})
    approvals = manager.list_pending_approvals()
    metrics = {**metrics,
        "uptime_seconds": max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds())),
        "active_runs": len(queue.get("active_runs", [])), "queued_runs": len(queue.get("queued_runs", [])),
        "waiting_runs": sum(row.get("status") == "WAITING_FOR_SLOT" for row in all_runs),
        "completed_runs": sum(row.get("status") == "COMPLETED" for row in all_runs),
        "failed_runs": sum(row.get("status") == "FAILED" for row in all_runs),
        "cancelled_runs": sum(row.get("status") == "CANCELLED" for row in all_runs),
        "waiting_approvals": len(approvals), "workspace_locks": len(queue.get("workspace_locks", [])),
        "token_usage": metrics.get("token_usage"),
        "db_size_bytes": (config.state_dir / "runs.sqlite3").stat().st_size if (config.state_dir / "runs.sqlite3").exists() else 0}
    return {
        "service_instance_id": instance_id, "service_state": service_state,
        "bridge_version": __version__, "codex_version": codex_version,
        "app_server_state": manager.state.value, "app_server_pid": health.get("server", {}).get("pid"),
        "scheduler_state": "HEALTHY" if health.get("registry", {}).get("accessible") else "DEGRADED",
        "queue_length": queue.get("queue_length", 0), "active_runs": len(queue.get("active_runs", [])),
        "waiting_approvals": len(approvals), "workspace_locks": len(queue.get("workspace_locks", [])),
        "db_health": bool(health.get("registry", {}).get("accessible")),
        "capability_compatibility": health.get("compatibility", {}), "metrics": metrics,
        "uptime_seconds": max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds())),
        "config": config.sanitized(),
        "config_fingerprint": hashlib.sha256(json.dumps(config.sanitized(), sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest(),
        "last_fatal_error": redact(last_fatal_error) if last_fatal_error else None,
    }


class ForegroundService:
    def __init__(self, config: ServiceConfig, *, fake_command: list[str] | None = None):
        self.config = config
        self.db_path = config.state_dir / "runs.sqlite3"
        self.instance_id = "svc_" + uuid.uuid4().hex[:16]
        self.started_at = _now()
        previous_state = service_status(config.state_dir)
        self.previous_crash_detected = previous_state.get("state") == "CRASHED"
        self.stop_event = threading.Event()
        self.manager: Any = None
        self.fake_command = fake_command
        self.codex_version: str | None = None
        self.process_identity = _process_identity(os.getpid())
        self._log_handlers: list[logging.Handler] = []
        self.capability_snapshot: dict[str, Any] = {"current": None, "previous": None, "changed": None}

    @staticmethod
    def _json_formatter(record: logging.LogRecord) -> str:
        return json.dumps({"time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname, "logger": record.name, "message": redact(record.getMessage())}, ensure_ascii=False)

    def _setup_logging(self) -> None:
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            self.config.log_dir / "service.log", maxBytes=self.config.log_max_bytes,
            backupCount=self.config.log_backup_count, encoding="utf-8")
        if self.config.structured_logs:
            class StructuredFormatter(logging.Formatter):
                def format(self, record: logging.LogRecord) -> str:
                    return ForegroundService._json_formatter(record)
            handler.setFormatter(StructuredFormatter())
        else:
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger = logging.getLogger("p4_codex_bridge")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        self._log_handlers.append(handler)
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(console)
        self._log_handlers.append(console)

    def _write_state(self, state: str, payload: dict[str, Any] | None = None, error: str | None = None) -> None:
        with _connect(self.db_path) as db:
            db.execute("""INSERT INTO bridge_service_state(singleton,instance_id,pid,process_identity,state,started_at,heartbeat_at,payload_json,last_fatal_error)
                VALUES(1,?,?,?,?,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET instance_id=excluded.instance_id,pid=excluded.pid,
                process_identity=excluded.process_identity,state=excluded.state,started_at=excluded.started_at,
                heartbeat_at=excluded.heartbeat_at,payload_json=excluded.payload_json,last_fatal_error=excluded.last_fatal_error""",
                (self.instance_id, os.getpid(), self.process_identity, state, self.started_at, _now(),
                 json.dumps(payload or {}, ensure_ascii=False), redact(error) if error else None))

    def _next_command(self) -> tuple[str, str] | None:
        with _connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT request_id,action FROM bridge_service_commands WHERE status='PENDING' ORDER BY created_at LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE bridge_service_commands SET status='PROCESSING' WHERE request_id=? AND status='PENDING'", (row["request_id"],))
            db.commit()
            return (row["request_id"], row["action"]) if row else None

    def _complete_command(self, request_id: str, status: str = "COMPLETED", error: str | None = None,
                          result: dict[str, Any] | None = None) -> None:
        with _connect(self.db_path) as db:
            db.execute("UPDATE bridge_service_commands SET status=?,completed_at=?,error=?,result_json=? WHERE request_id=?",
                       (status, _now(), redact(error)[:300] if error else None,
                       json.dumps(result, ensure_ascii=False) if result is not None else None, request_id))

    def _recover_runtime_commands(self) -> None:
        """Never replay a claimed command after a crash: its side effect may have happened."""
        cutoff = datetime.fromtimestamp(time.time() - 24 * 3600, timezone.utc).isoformat()
        with _connect(self.db_path) as db:
            db.execute("UPDATE bridge_runtime_commands SET status='FAILED',completed_at=?,error='service restarted after claim; outcome is unknown' WHERE status='CLAIMED'", (_now(),))
            db.execute("UPDATE bridge_runtime_commands SET status='EXPIRED',completed_at=?,error='command expired before processing' WHERE status='SUBMITTED' AND submitted_at<?", (_now(), cutoff))

    def _claim_runtime_command(self) -> dict[str, Any] | None:
        with _connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT command_id,command_type,payload FROM bridge_runtime_commands WHERE status='SUBMITTED' ORDER BY submitted_at,command_id LIMIT 1").fetchone()
            if row:
                updated = db.execute("UPDATE bridge_runtime_commands SET status='CLAIMED',claimed_by=?,claimed_at=?,payload='' WHERE command_id=? AND status='SUBMITTED'",
                                     (self.instance_id, _now(), row["command_id"]))
                if updated.rowcount != 1:
                    return None
            return dict(row) if row else None

    def _complete_runtime_command(self, command_id: str, *, result: dict[str, Any] | None = None,
                                  error: str | None = None) -> None:
        with _connect(self.db_path) as db:
            db.execute("UPDATE bridge_runtime_commands SET status=?,completed_at=?,result=?,error=? WHERE command_id=? AND status='CLAIMED' AND claimed_by=?",
                ("FAILED" if error else "COMPLETED", _now(), json.dumps(result, ensure_ascii=False, separators=(",", ":")) if result is not None else None,
                 redact(error)[:300] if error else None, command_id, self.instance_id))

    def _process_runtime_command(self, command: dict[str, Any]) -> None:
        import json
        try:
            payload = json.loads(command["payload"])
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            if len(command["payload"].encode("utf-8")) > 1024 * 1024:
                raise ValueError("command payload exceeds the 1 MiB limit")
            if command["command_type"] == "SUBMIT_EXEC_RUN":
                from .service_client import ExecRunSubmission
                from .security import RunSecurityPolicy
                from .models import ApprovalPolicy, SandboxMode
                from .permissions import CodexPermissions
                raw_permissions = payload.pop("permissions", None)
                raw_security = payload.pop("security_policy", None)
                security_policy = RunSecurityPolicy.from_dict(raw_security)
                permissions = None
                if raw_permissions is not None:
                    if set(raw_permissions) != {"sandbox", "approval_policy", "writable_roots", "network_access"}:
                        raise ValueError("invalid permission fields")
                    permissions = CodexPermissions(SandboxMode(raw_permissions["sandbox"]),
                        ApprovalPolicy(raw_permissions["approval_policy"]), tuple(raw_permissions["writable_roots"]), raw_permissions["network_access"])
                prompt = payload.pop("prompt")
                cwd = payload.pop("cwd")
                profile = payload.pop("profile")
                model = payload.pop("model")
                timeout_seconds = payload.pop("timeout_seconds")
                config_policy = payload.pop("config_policy")
                metadata = payload.pop("metadata")
                access_mode = payload.pop("access_mode")
                resource_priority = payload.pop("resource_priority")
                output_schema = payload.pop("output_schema")
                if payload:
                    raise ValueError("unknown exec submission fields")
                validated = ExecRunSubmission(prompt=prompt, cwd=cwd, profile=profile, model=model,
                    timeout_seconds=timeout_seconds, config_policy=config_policy, metadata=metadata,
                    access_mode=access_mode, resource_priority=resource_priority,
                    permissions=permissions, output_schema=output_schema, security_policy=security_policy).payload()
                record = self.exec_bridge.start(validated["prompt"], cwd=validated["cwd"], profile=validated["profile"],
                    model=validated["model"], timeout_seconds=validated["timeout_seconds"],
                    config_policy=validated["config_policy"], metadata=validated["metadata"],
                    permissions=permissions, output_schema=validated["output_schema"],
                    access_mode=validated["access_mode"], resource_priority=validated["resource_priority"],
                    security_policy=security_policy)
                result = {"bridge_run_id": record.bridge_run_id, "status": record.status.value, "backend": "exec"}
            elif command["command_type"] == "CREATE_THREAD":
                from .service_client import CreateThreadRequest
                from .security import RunSecurityPolicy
                raw_security = payload.pop("security_policy", None)
                security_policy = RunSecurityPolicy.from_dict(raw_security)
                required = {"cwd", "profile", "model", "sandbox", "approval_policy", "config_policy", "metadata"}
                if set(payload) != required:
                    raise ValueError("invalid create-thread fields")
                payload = CreateThreadRequest(**payload, security_policy=security_policy).payload()
                root = Path(payload["cwd"]).resolve(strict=True)
                if not root.is_dir() or not any(root == allowed or allowed in root.parents for allowed in self.config.allowed_roots):
                    raise ValueError("cwd is outside configured service allowed roots")
                payload["cwd"] = str(root)
                payload.pop("security_policy", None)
                thread = self.manager.create_thread(**payload, security_policy=security_policy)
                result = {"thread_id": thread.thread_id, "status": "CREATED", "cwd": thread.cwd}
            elif command["command_type"] == "START_TURN":
                from .service_client import StartTurnRequest
                from .security import RunSecurityPolicy
                raw_security = payload.pop("security_policy", None)
                security_policy = RunSecurityPolicy.from_dict(raw_security) if raw_security is not None else None
                required = {"thread_id", "prompt", "timeout_seconds", "metadata", "access_mode", "resource_priority"}
                if set(payload) != required:
                    raise ValueError("invalid start-turn fields")
                payload = StartTurnRequest(**payload, security_policy=security_policy).payload()
                thread_id = payload.pop("thread_id")
                prompt = payload.pop("prompt")
                timeout_seconds = payload.pop("timeout_seconds")
                payload.pop("security_policy", None)
                turn = self.manager.start_turn(thread_id, prompt, timeout=timeout_seconds,
                    security_policy=security_policy, **payload)
                result = {"bridge_run_id": turn.bridge_run_id, "thread_id": turn.thread_id,
                          "turn_id": turn.turn_id, "status": turn.status.value}
            else:
                raise ValueError("unsupported runtime command")
            self._complete_runtime_command(command["command_id"], result=result)
        except Exception as exc:
            self._complete_runtime_command(command["command_id"], error=f"{type(exc).__name__}: {exc}")

    def _start_fake_demo(self) -> dict[str, Any]:
        if not self.fake_command or not self.manager:
            raise RuntimeError("service demo is available only with service run --fake")
        from .security import ProjectTrust, RunSecurityPolicy
        fake_security = RunSecurityPolicy(project_trust=ProjectTrust.TRUSTED,
            allow_external_mcps=True, allow_side_effect_mcps=True,
            explicit_risk_acknowledgement=True, policy_id="offline-fake-demo")
        alternate = self.config.state_dir / "demo-workspace"
        alternate.mkdir(parents=True, exist_ok=True)
        jobs = [
            (self.config.cwd, "WRITE", "ImplementationAgent", "DEMO-WRITE"),
            (self.config.cwd, "READ", "ValidationAgent", "DEMO-LOCK"),
            (alternate, "READ", "AnalysisAgent", "DEMO-OTHER-WORKSPACE"),
        ]
        run_ids = []
        for cwd, access, agent, task in jobs:
            thread = self.manager.create_thread(cwd=cwd, metadata={"agent_name": agent, "agent_role": "demo", "task_key": task},
                                                security_policy=fake_security)
            turn = self.manager.start_turn(thread.thread_id, "FAKE_SERVICE_DEMO", metadata={
                "agent_name": agent, "agent_role": "demo", "task_key": task}, access_mode=access)
            run_ids.append(turn.bridge_run_id)
        return {"run_ids": run_ids, "note": "fake protocol only; no model inference"}

    def run(self) -> int:
        self._setup_logging()
        _ensure_service_schema(self.db_path)
        self._recover_runtime_commands()
        from .runtime_manager import CodexRuntimeManager, RuntimeState
        limits = self.config.runtime_limits
        command = self.fake_command
        capability_set = None
        if self.fake_command:
            from .app_server_capabilities import AppServerCapabilitySet, CapabilityStatus, FEATURE_METHODS
            capability_set = AppServerCapabilitySet({key: CapabilityStatus.SUPPORTED for key in FEATURE_METHODS}, "explicit-fake-protocol", "fake")
        if command is None:
            if os.environ.get("P4_CODEX_BRIDGE_CODEX_EXECUTABLE"):
                command = resolve_codex_command() + ["app-server", "--listen", "stdio://"]
            elif self.config.codex_executable:
                command = [self.config.codex_executable, "app-server", "--listen", "stdio://"]
        self.manager = CodexRuntimeManager(cwd=self.config.cwd, database_path=self.db_path,
            max_active_turns=limits.app_server_max_active, max_threads=limits.max_active_threads,
            max_pending_requests=limits.max_queue_size, startup_timeout=self.config.startup_timeout_seconds,
            command=command, runtime_limits=limits, approval_timeout_seconds=self.config.approval_timeout_seconds,
            capability_set=capability_set)
        old_handlers: dict[int, Any] = {}
        def request_shutdown(signum, frame):
            self.stop_event.set()
        for sig in (signal.SIGINT, getattr(signal, "SIGBREAK", None), signal.SIGTERM):
            if sig is not None:
                try:
                    old_handlers[sig] = signal.signal(sig, request_shutdown)
                except (ValueError, OSError):
                    pass
        try:
            try:
                if self.fake_command:
                    self.codex_version = "FAKE"
                else:
                    version_text = probe(["--version"], timeout=5)
                    self.codex_version = next((line.strip() for line in version_text.splitlines() if "codex" in line.lower()), None)
            except Exception: self.codex_version = None
            logging.getLogger("p4_codex_bridge.service").info("service starting instance=%s", self.instance_id)
            self.manager.start()
            from .client import CodexBridge
            self.exec_bridge = CodexBridge(state_dir=self.config.state_dir, allowed_roots=self.config.allowed_roots)
            self.capability_snapshot = _persist_capability_snapshot(self.db_path, self.started_at,
                self.codex_version, self.manager.get_capabilities())
            # Publish only after manager.start owns the OS singleton lock. A
            # rejected duplicate start must never overwrite the live instance.
            self._write_state("RECOVERING", {"previous_service_crash_detected": self.previous_crash_detected})
            while not self.stop_event.is_set():
                runtime_command = self._claim_runtime_command()
                if runtime_command:
                    self._process_runtime_command(runtime_command)
                command_item = self._next_command()
                if command_item:
                    request_id, action = command_item
                    if action == "stop":
                        self._complete_command(request_id)
                        self.stop_event.set()
                    elif action == "recover":
                        try:
                            result = self.manager.recover(dry_run=False)
                            self._complete_command(request_id, error=None if result else None)
                        except Exception as exc:
                            self._complete_command(request_id, "FAILED", type(exc).__name__)
                    elif action == "demo":
                        try:
                            self._complete_command(request_id, result=self._start_fake_demo())
                        except Exception as exc:
                            self._complete_command(request_id, "FAILED", type(exc).__name__)
                state = "HEALTHY" if self.manager.state == RuntimeState.HEALTHY else "DEGRADED"
                try:
                    snapshot = service_snapshot(self.config, self.manager, self.instance_id, self.started_at, self.codex_version, state)
                    snapshot["previous_service_crash_detected"] = self.previous_crash_detected
                    snapshot["capability_snapshot"] = self.capability_snapshot
                    self._write_state(state, snapshot)
                except Exception as exc:
                    logging.getLogger("p4_codex_bridge.service").error("health snapshot failed class=%s", type(exc).__name__)
                    self._write_state("DEGRADED", error=type(exc).__name__)
                self.stop_event.wait(0.5)
            self._write_state("STOPPING")
            shutdown_mode = self.config.shutdown_policy
            if shutdown_mode == "WAIT":
                deadline = time.monotonic() + self.config.shutdown_timeout_seconds
                last_shutdown_heartbeat = 0.0
                while time.monotonic() < deadline:
                    try:
                        active = self.manager.scheduler.resources(self.manager.runtime_limits)["active_runs"]
                    except Exception:
                        active = []
                    if not active:
                        break
                    if time.monotonic() - last_shutdown_heartbeat >= 1:
                        stopping_snapshot = service_snapshot(self.config, self.manager, self.instance_id,
                            self.started_at, self.codex_version, "STOPPING")
                        stopping_snapshot["previous_service_crash_detected"] = self.previous_crash_detected
                        self._write_state("STOPPING", stopping_snapshot)
                        last_shutdown_heartbeat = time.monotonic()
                    time.sleep(0.1)
                else:
                    shutdown_mode = "INTERRUPT"
            self.manager.stop(mode=shutdown_mode, timeout=self.config.shutdown_timeout_seconds)
            snapshot = service_snapshot(self.config, self.manager, self.instance_id, self.started_at, self.codex_version, "STOPPED")
            snapshot["previous_service_crash_detected"] = self.previous_crash_detected
            self._write_state("STOPPED", snapshot)
            logging.getLogger("p4_codex_bridge.service").info("service stopped instance=%s", self.instance_id)
            return 0
        except Exception as exc:
            lock = getattr(self.manager, "_singleton", None)
            if lock is not None and getattr(lock, "file", None) is not None:
                self._write_state("CRASHED", error=type(exc).__name__)
            logging.getLogger("p4_codex_bridge.service").error("service crashed class=%s", type(exc).__name__)
            try:
                self.manager.stop(mode="FORCE", timeout=2)
            except Exception:
                pass
            return 1
        finally:
            for sig, handler in old_handlers.items():
                try: signal.signal(sig, handler)
                except (ValueError, OSError): pass
            logger = logging.getLogger("p4_codex_bridge")
            for handler in self._log_handlers:
                logger.removeHandler(handler)
                handler.close()
            self._log_handlers.clear()


def request_service_action(state_dir: str | Path, action: str, *, timeout: float = 10) -> dict[str, Any]:
    if action not in {"stop", "recover", "demo"}:
        raise ValueError("unsupported service action")
    root = Path(state_dir).expanduser().resolve()
    db_path = root / "runs.sqlite3"
    state = read_service_state(root)
    if not state.get("running"):
        raise ServiceUnavailableError("P4-Codex-Bridge service is not running")
    if action == "demo" and state.get("codex_version") != "FAKE":
        raise RuntimeError("service demo can only target a fake protocol service")
    request_id = "svcctl_" + uuid.uuid4().hex
    with _connect(db_path) as db:
        db.execute("INSERT INTO bridge_service_commands(request_id,action,status,created_at) VALUES(?,?, 'PENDING',?)", (request_id, action, _now()))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if action == "stop":
            state_now = service_status(root)
            if not state_now.get("running") and state_now.get("state") == "STOPPED":
                return {"request_id": request_id, "action": action, "status": "COMPLETED"}
            if not state_now.get("running") and state_now.get("state") == "CRASHED":
                return {"request_id": request_id, "action": action, "status": "FAILED", "error": "service stopped unexpectedly"}
            time.sleep(0.1)
            continue
        with _connect(db_path) as db:
            row = db.execute("SELECT status,error,result_json FROM bridge_service_commands WHERE request_id=?", (request_id,)).fetchone()
        if row and row["status"] in {"COMPLETED", "FAILED"}:
            result = json.loads(row["result_json"]) if row["result_json"] else None
            return {"request_id": request_id, "action": action, "status": row["status"], "error": row["error"], "result": result}
        time.sleep(0.1)
    return {"request_id": request_id, "action": action, "status": "PENDING"}


def launch_service(*, config_path: str | Path | None, state_dir: str | Path | None,
                   fake: bool = False, timeout: float = 15) -> dict[str, Any]:
    """Restart through a new foreground-service process; never restart in place."""
    import subprocess
    root = ServiceConfig.load(config_path, state_dir=state_dir).state_dir
    before = service_status(root)
    old_id = before.get("instance_id")
    if before.get("running"):
        stopped = request_service_action(root, "stop", timeout=timeout)
        if stopped.get("status") != "COMPLETED":
            raise TimeoutError("existing service did not stop before restart timeout")
    command = [sys.executable, "-m", "p4_codex_bridge", "service", "run"]
    if config_path:
        command.extend(["--config", str(Path(config_path).resolve())])
    if state_dir:
        command.extend(["--state-dir", str(Path(state_dir).resolve())])
    if fake:
        command.append("--fake")
    options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL, "shell": False, "cwd": str(Path.cwd())}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        options["startupinfo"] = startup
    else:
        options["start_new_session"] = True
    child = subprocess.Popen(command, **options)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = service_status(root)
        if current.get("instance_id") != old_id and current.get("running") and current.get("state") in {"HEALTHY", "DEGRADED"}:
            return {"started": True, "instance_id": current.get("instance_id"), "pid": current.get("pid"), "state": current.get("state")}
        if child.poll() is not None:
            raise RuntimeError("new service process exited before becoming healthy")
        time.sleep(0.1)
    raise TimeoutError("new service did not become healthy before restart timeout")


def service_status(state_dir: str | Path) -> dict[str, Any]:
    state = read_service_state(state_dir)
    if not state.get("running"):
        return state
    db_path = Path(state_dir) / "runs.sqlite3"
    try:
        with _connect(db_path) as db:
            row = db.execute("SELECT payload_json FROM bridge_service_state WHERE singleton=1").fetchone()
            payload = json.loads(row[0]) if row else {}
        return {**payload, **state}
    except Exception:
        state["state"] = "DEGRADED"
        state["reason"] = "service snapshot unavailable"
        return state


def service_metrics(state_dir: str | Path) -> dict[str, Any]:
    state = service_status(state_dir)
    metrics = state.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return {"available": False, "reason": "service metrics have not been recorded"}


_SAFE_RETENTION_STATUSES = ("COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED", "STOPPED", "TIMED_OUT")


def database_health(state_dir: str | Path, *, retention_days: int = 30) -> dict[str, Any]:
    """Read-only SQLite and cleanup health; never creates a missing state DB."""
    path = Path(state_dir) / "runs.sqlite3"
    if not path.is_file():
        return {"available": False, "integrity": "NOT_CHECKED", "schema_version": None,
                "migration_status": "DATABASE_ABSENT", "size_bytes": 0, "pending_cleanup": 0}
    try:
        with _connect(path) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            bridge_version = None
            if "bridge_schema" in tables:
                row = db.execute("SELECT MAX(version) FROM bridge_schema").fetchone()
                bridge_version = row[0]
            stale = 0
            if "scheduler_payloads" in tables and "scheduler_runs" in tables:
                stale += db.execute("SELECT COUNT(*) FROM scheduler_payloads p LEFT JOIN scheduler_runs r USING(bridge_run_id) WHERE r.bridge_run_id IS NULL").fetchone()[0]
            if "runtime_approvals" in tables:
                stale += db.execute("SELECT COUNT(*) FROM runtime_approvals WHERE status='STALE_LOCAL'").fetchone()[0]
            cutoff = datetime.now(timezone.utc).timestamp() - max(0, retention_days) * 86400
            pending = 0
            for table, time_col in (("scheduler_runs", "submitted_at"), ("runs", "started_at")):
                if table in tables:
                    age_expr = f"COALESCE(finished_at,{time_col})" if table == "scheduler_runs" else time_col
                    rows = db.execute(f"SELECT COUNT(*) FROM {table} WHERE status IN ({','.join('?' for _ in _SAFE_RETENTION_STATUSES)}) AND {age_expr} < ?",
                                      (*_SAFE_RETENTION_STATUSES, datetime.fromtimestamp(cutoff, timezone.utc).isoformat())).fetchone()
                    pending += int(rows[0])
        migration_status = ("INTEGRITY_ERROR" if integrity != "ok" else
                            "CURRENT" if bridge_version == 2 else
                            "MIGRATION_REQUIRED" if bridge_version == 1 else
                            "UNKNOWN_SCHEMA")
        return {"available": True, "integrity": integrity,
                "schema_version": {"bridge_schema": bridge_version, "sqlite_user_version": _sqlite_user_version(path)},
                "migration_status": migration_status,
                "size_bytes": path.stat().st_size, "pending_cleanup": pending,
                "stale_records": stale, "oversized": path.stat().st_size > 1024 * 1024 * 1024}
    except (sqlite3.Error, OSError, ValueError) as exc:
        return {"available": False, "integrity": "ERROR", "migration_status": type(exc).__name__,
                "size_bytes": path.stat().st_size if path.exists() else 0, "pending_cleanup": None}


def _sqlite_user_version(path: Path) -> int:
    db = sqlite3.connect(path, timeout=5)
    try:
        return int(db.execute("PRAGMA user_version").fetchone()[0])
    finally:
        db.close()


def _persist_capability_snapshot(db_path: Path, started_at: str, codex_version: str | None,
                                 capabilities: dict[str, Any]) -> dict[str, Any]:
    # Store only the small status record; never persist full schemas or config.
    clean = {"bridge_can_support": capabilities.get("bridge_can_support", []),
             "codex_supports": capabilities.get("codex_supports", {}),
             "effective_available": capabilities.get("effective_available"),
             "protocol_version": capabilities.get("protocol_version"),
             "bridge_version": capabilities.get("bridge_version")}
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    previous = None
    with _connect(db_path) as db:
        row = db.execute("SELECT started_at,codex_version,protocol_version,capability_json,capability_fingerprint FROM bridge_service_snapshots ORDER BY snapshot_id DESC LIMIT 1").fetchone()
        if row:
            previous = {"started_at": row[0], "codex_version": row[1], "protocol_version": row[2],
                        "capabilities": json.loads(row[3]), "fingerprint": row[4]}
        db.execute("INSERT INTO bridge_service_snapshots(started_at,codex_version,protocol_version,capability_json,capability_fingerprint) VALUES(?,?,?,?,?)",
                   (started_at, codex_version, clean.get("protocol_version"), encoded, fingerprint))
        db.execute("DELETE FROM bridge_service_snapshots WHERE snapshot_id NOT IN (SELECT snapshot_id FROM bridge_service_snapshots ORDER BY snapshot_id DESC LIMIT 2)")
    current = {"started_at": started_at, "codex_version": codex_version,
               "protocol_version": clean.get("protocol_version"), "capabilities": clean, "fingerprint": fingerprint}
    return {"current": current, "previous": previous,
            "changed": previous["fingerprint"] != fingerprint if previous else None}


def maintenance_report(state_dir: str | Path, config: ServiceConfig, *, dry_run: bool = True) -> dict[str, Any]:
    """Report or purge old resolved operational rows; active/uncertain work is retained."""
    path = Path(state_dir) / "runs.sqlite3"
    if not path.is_file():
        return {"available": False, "dry_run": dry_run, "database": str(path), "would_delete": {}, "deleted": {}}
    cutoff = datetime.now(timezone.utc).timestamp() - config.retention_days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
    counts = {"runs": 0, "scheduler_runs": 0, "scheduler_payloads": 0, "events": 0, "approvals": 0,
              "runtime_approvals": 0, "control_requests": 0, "runtime_servers": 0, "orphan_payloads": 0}
    result_files: dict[str, Path] = {}
    with _connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        run_rows: dict[str, dict[str, Any]] = {}
        if "scheduler_runs" in tables:
            rows = db.execute("SELECT bridge_run_id,turn_id,status,COALESCE(finished_at,submitted_at) AS age FROM scheduler_runs WHERE status IN (?,?,?,?,?,?) ORDER BY COALESCE(finished_at,submitted_at) DESC,bridge_run_id DESC", _SAFE_RETENTION_STATUSES).fetchall()
            for row in rows:
                run_rows[row["bridge_run_id"]] = dict(row)
        if "runs" in tables:
            rows = db.execute("SELECT bridge_run_id,turn_id,status,started_at AS age,result_path FROM runs WHERE status IN (?,?,?,?,?,?) ORDER BY started_at DESC,bridge_run_id DESC", _SAFE_RETENTION_STATUSES).fetchall()
            for row in rows:
                existing = run_rows.get(row["bridge_run_id"], {})
                run_rows[row["bridge_run_id"]] = {**dict(row), **existing}
                result_path = row["result_path"]
                if result_path:
                    result_files[row["bridge_run_id"]] = Path(result_path)
        ordered = sorted(run_rows.items(), key=lambda item: (str(item[1].get("age") or ""), item[0]), reverse=True)
        keep_ids = {run_id for run_id, _ in ordered[:config.max_completed_runs]} if config.max_completed_runs else set()
        cutoff_ids = {run_id for run_id, row in ordered if str(row.get("age") or "") < cutoff_iso}
        purge_ids = cutoff_ids | {run_id for run_id, _ in ordered if run_id not in keep_ids}
        # Never purge LOST/UNKNOWN or any non-terminal scheduler state.
        purge_ids = {run_id for run_id in purge_ids if run_rows[run_id].get("status") in _SAFE_RETENTION_STATUSES}
        for run_id, row in ordered:
            if run_id in purge_ids or not row.get("turn_id"):
                continue
            for table, clause, key in (("turn_events", "bridge_run_id", run_id), ("runtime_events", "turn_id", row["turn_id"])):
                if table not in tables:
                    continue
                if config.max_events_per_run == 0:
                    stale_events = db.execute(f"SELECT sequence FROM {table} WHERE {clause}=?", (key,)).fetchall()
                else:
                    stale_events = db.execute(f"SELECT sequence FROM {table} WHERE {clause}=? ORDER BY sequence DESC LIMIT -1 OFFSET ?", (key, config.max_events_per_run)).fetchall()
                event_ids = [int(item[0]) for item in stale_events]
                counts["events"] += len(event_ids)
                if not dry_run and event_ids:
                    db.executemany(f"DELETE FROM {table} WHERE sequence=?", ((event_id,) for event_id in event_ids))
        for run_id in purge_ids:
            for table in ("scheduler_payloads", "scheduler_runs", "runs"):
                if table in tables:
                    counts[table] += db.execute(f"SELECT COUNT(*) FROM {table} WHERE bridge_run_id=?", (run_id,)).fetchone()[0]
            for table in ("turn_events", "runtime_events"):
                if table in tables:
                    counts["events"] += db.execute(f"SELECT COUNT(*) FROM {table} WHERE bridge_run_id=?" if table == "turn_events" else f"SELECT COUNT(*) FROM {table} WHERE turn_id=?", (run_id if table == "turn_events" else run_rows[run_id].get("turn_id"),)).fetchone()[0]
            for table in ("approvals", "runtime_approvals"):
                if table in tables:
                    if table == "approvals":
                        counts[table] += db.execute("SELECT COUNT(*) FROM approvals WHERE turn_id=? AND status NOT IN ('PENDING','DECISION')", (run_rows[run_id].get("turn_id"),)).fetchone()[0]
                    else:
                        counts[table] += db.execute("SELECT COUNT(*) FROM runtime_approvals WHERE bridge_run_id=? AND status NOT IN ('PENDING','DECISION')", (run_id,)).fetchone()[0]
        if "scheduler_payloads" in tables and "scheduler_runs" in tables:
            counts["orphan_payloads"] = db.execute("SELECT COUNT(*) FROM scheduler_payloads p LEFT JOIN scheduler_runs r USING(bridge_run_id) WHERE r.bridge_run_id IS NULL").fetchone()[0]
        if "bridge_service_commands" in tables:
            counts["control_requests"] = db.execute("SELECT COUNT(*) FROM bridge_service_commands WHERE status IN ('COMPLETED','FAILED') AND created_at < ?", (cutoff_iso,)).fetchone()[0]
        if "runtime_servers" in tables:
            counts["runtime_servers"] = db.execute("SELECT COUNT(*) FROM runtime_servers WHERE status IN ('STOPPED','FAILED','CRASHED') AND started_at < ?", (cutoff_iso,)).fetchone()[0]
        if not dry_run:
            for run_id in purge_ids:
                turn_id = run_rows[run_id].get("turn_id")
                for table in ("turn_events", "runtime_events"):
                    if table in tables:
                        db.execute(f"DELETE FROM {table} WHERE bridge_run_id=?" if table == "turn_events" else f"DELETE FROM {table} WHERE turn_id=?", (run_id if table == "turn_events" else turn_id,))
                for table in ("approvals", "runtime_approvals"):
                    if table in tables:
                        if table == "approvals":
                            db.execute("DELETE FROM approvals WHERE turn_id=? AND status NOT IN ('PENDING','DECISION')", (turn_id,))
                        else:
                            db.execute("DELETE FROM runtime_approvals WHERE bridge_run_id=? AND status NOT IN ('PENDING','DECISION')", (run_id,))
                for table in ("scheduler_payloads", "scheduler_runs", "runs"):
                    if table in tables:
                        db.execute(f"DELETE FROM {table} WHERE bridge_run_id=?", (run_id,))
            if "scheduler_payloads" in tables and "scheduler_runs" in tables:
                db.execute("DELETE FROM scheduler_payloads WHERE bridge_run_id NOT IN (SELECT bridge_run_id FROM scheduler_runs)")
            if "bridge_service_commands" in tables:
                db.execute("DELETE FROM bridge_service_commands WHERE status IN ('COMPLETED','FAILED') AND created_at < ?", (cutoff_iso,))
            if "runtime_servers" in tables:
                db.execute("DELETE FROM runtime_servers WHERE status IN ('STOPPED','FAILED','CRASHED') AND started_at < ?", (cutoff_iso,))
    if not dry_run:
        for run_id in purge_ids:
            result_path = result_files.get(run_id)
            if not result_path:
                continue
            try:
                resolved = result_path.resolve()
                resolved.relative_to(Path(state_dir).resolve())
                resolved.unlink(missing_ok=True)
            except (OSError, ValueError):
                continue
    return {"available": True, "dry_run": dry_run, "database": str(path),
            "retention_days": config.retention_days, "cutoff": cutoff_iso,
            "would_delete": counts, "deleted": {} if dry_run else counts,
            "vacuum": "NOT_RUN", "database_health": database_health(state_dir, retention_days=config.retention_days)}


def validate_config(path: str | Path | None = None, *, state_dir: str | Path | None = None) -> dict[str, Any]:
    config = ServiceConfig.load(path, state_dir=state_dir)
    return {"valid": True, "config": config.sanitized(), "source": str(Path(path).resolve()) if path else "defaults/environment"}


def fake_app_server_command() -> list[str]:
    """Minimal no-inference protocol endpoint for service lifecycle demos/tests."""
    script = r'''import json,sys,threading,time
lock=threading.Lock(); thread_count=0; turn_count=0
def send(value):
 with lock: print(json.dumps(value),flush=True)
def finish(tid,trid):
 time.sleep(5); p={"threadId":tid,"turnId":trid}
 send({"jsonrpc":"2.0","method":"turn/started","params":p})
 send({"jsonrpc":"2.0","method":"item/agentMessage/delta","params":{**p,"delta":"Fake agent working\\n"}})
 send({"jsonrpc":"2.0","method":"item/completed","params":{**p,"item":{"id":"item-"+trid,"type":"agentMessage","text":"Fake agent completed"}}})
 send({"jsonrpc":"2.0","method":"turn/completed","params":{**p,"turn":{"status":"completed"}}})
for line in sys.stdin:
 try: message=json.loads(line)
 except Exception: continue
 method=message.get("method"); request_id=message.get("id"); params=message.get("params",{})
 if method=="initialize":
  send({"jsonrpc":"2.0","id":request_id,"result":{"protocolVersion":"fake-v2","serverInfo":{"name":"p4-fake-app-server","version":"0"}}})
 elif method=="thread/start":
  thread_count+=1; tid="fake-thread-"+str(thread_count)
  send({"jsonrpc":"2.0","id":request_id,"result":{"thread":{"id":tid,"cwd":params.get("cwd")}}})
 elif method=="turn/start":
  turn_count+=1; trid="fake-turn-"+str(turn_count); tid=params.get("threadId")
  send({"jsonrpc":"2.0","id":request_id,"result":{"turn":{"id":trid}}})
  threading.Thread(target=finish,args=(tid,trid),daemon=True).start()
 elif method=="turn/interrupt":
  send({"jsonrpc":"2.0","id":request_id,"result":{}})
'''
    return [sys.executable, "-u", "-c", script]


def doctor_report(config: ServiceConfig) -> dict[str, Any]:
    import platform
    import subprocess
    from .runtime import resolve_codex_command
    from .app_server_capabilities import (CapabilityStatus, REQUIRED_APP_SERVER_CAPABILITIES,
        OPTIONAL_APP_SERVER_CAPABILITIES, discover_app_server_capabilities)

    checks: dict[str, Any] = {"python": platform.python_version(), "bridge_version": __version__}
    try:
        from importlib.metadata import version
        checks["installation"] = {"distribution": "p4-codex-bridge", "version": version("p4-codex-bridge")}
    except Exception:
        checks["installation"] = {"distribution": "p4-codex-bridge", "version": None, "source_checkout": True}

    entry_dir = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    adjacent_python = entry_dir / ("python.exe" if os.name == "nt" else "python")
    module_check: dict[str, Any] = {"status": "UNKNOWN", "interpreter": sys.executable}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "p4_codex_bridge", "--version"],
            capture_output=True, text=True, timeout=5, shell=False,
        )
        module_check.update(status="PASS" if result.returncode == 0 else "FAIL",
                            exit_code=result.returncode, output=(result.stdout.strip() or None))
    except subprocess.TimeoutExpired:
        module_check.update(status="FAIL", error_class="TimeoutExpired")
    except Exception as exc:
        module_check.update(status="FAIL", error_class=type(exc).__name__)

    cmd_path = entry_dir / "p4-codex.cmd"
    cmd_status = "PASS" if os.name == "nt" and cmd_path.is_file() and adjacent_python.is_file() else "NOT_INSTALLED"
    exe_path = entry_dir / "p4-codex.exe"
    checks["entrypoints"] = {
        "module_entrypoint": module_check,
        "cmd_launcher": {
            "status": cmd_status,
            "path": str(cmd_path) if cmd_path.is_file() else None,
            "python_path": str(adjacent_python) if adjacent_python.is_file() else None,
            "executed_by_doctor": False,
        },
        "console_script_exe": {
            "status": "UNKNOWN" if exe_path.is_file() else "NOT_INSTALLED",
            "path": str(exe_path) if exe_path.is_file() else None,
            "executed_by_doctor": False,
            "note": "Not launched automatically; this console-script executable is optional and may hang in some Windows environments.",
        },
    }

    try:
        command = resolve_codex_command() if os.environ.get("P4_CODEX_BRIDGE_CODEX_EXECUTABLE") or not config.codex_executable else [config.codex_executable]
        environment = codex_environment()
        version_result = subprocess.run(command + ["--version"], capture_output=True, text=True, timeout=8, shell=False,
                                        env=environment)
        checks["codex"] = {"available": version_result.returncode == 0,
                           "version": next((line.strip() for line in version_result.stdout.splitlines() if line.strip()), None)}
        login = subprocess.run(command + ["login", "status"], capture_output=True, text=True, timeout=8, shell=False,
                                env=environment)
        checks["chatgpt_login"] = {"available": login.returncode == 0}
        server = subprocess.run(command + ["app-server", "--help"], capture_output=True, text=True, timeout=8, shell=False,
                                env=environment)
        checks["app_server"] = {"available": server.returncode == 0}
        capability_set = discover_app_server_capabilities(command=command, timeout=8)
        required = REQUIRED_APP_SERVER_CAPABILITIES
        checks["app_server_preflight"] = {**capability_set.to_dict(),
            "app_server_schema_source": capability_set.source,
            "app_server_schema_verified": capability_set.schema_snapshot is not None,
            "app_server_schema_snapshot": capability_set.schema_snapshot.to_dict() if capability_set.schema_snapshot else None,
            "required_features": {name: capability_set.status(name).value for name in required},
            "app_server_required_capabilities": {name: capability_set.status(name).value for name in required},
            "optional_features": {name: capability_set.status(name).value for name in OPTIONAL_APP_SERVER_CAPABILITIES},
            "app_server_optional_capabilities": {name: capability_set.status(name).value for name in OPTIONAL_APP_SERVER_CAPABILITIES},
            "protocol_compatible": all(capability_set.status(name) in {CapabilityStatus.SUPPORTED, CapabilityStatus.SUPPORTED_WITH_LIMITATIONS} for name in required)}
    except Exception as exc:
        checks["codex"] = {"available": False, "error_class": type(exc).__name__}
        checks["chatgpt_login"] = {"available": False}
        checks["app_server"] = {"available": False}
        checks["app_server_preflight"] = {"source": "NOT_AVAILABLE", "app_server_schema_source": "NOT_AVAILABLE",
            "app_server_schema_verified": False, "app_server_schema_snapshot": None,
            "app_server_required_capabilities": {name: "UNKNOWN" for name in REQUIRED_APP_SERVER_CAPABILITIES},
            "app_server_optional_capabilities": {name: "UNKNOWN" for name in OPTIONAL_APP_SERVER_CAPABILITIES},
            "protocol_compatible": None,
                                          "status": "UNKNOWN", "error": type(exc).__name__}

    probe_path = config.state_dir
    while not probe_path.exists() and probe_path != probe_path.parent:
        probe_path = probe_path.parent
    checks["state_dir"] = str(config.state_dir)
    checks["state_dir_writable"] = bool(probe_path.exists() and os.access(probe_path, os.W_OK))
    checks["config_valid"] = True
    checks["service"] = service_status(config.state_dir)
    checks["database"] = database_health(config.state_dir, retention_days=config.retention_days)
    db_ok = (not checks["database"].get("available") or
             (checks["database"].get("integrity") == "ok" and
              checks["database"].get("migration_status") in {"CURRENT", "MIGRATION_REQUIRED"}))
    checks["permissions"] = {"state_dir_write_access_best_effort": checks["state_dir_writable"],
                             "note": "ACL isolation is not verified by this read-only check"}
    checks["capabilities"] = {"app_server_available": checks.get("app_server", {}).get("available", False),
                              "app_server_preflight": checks.get("app_server_preflight", {}),
                              "exec_help_available": False}
    if checks.get("codex", {}).get("available"):
        try:
            help_result = subprocess.run(command + ["exec", "--help"], capture_output=True, text=True,
                                         timeout=8, shell=False, env=codex_environment())
            checks["capabilities"]["exec_help_available"] = help_result.returncode == 0
        except Exception:
            pass
    checks["ok"] = bool(checks.get("state_dir_writable") and db_ok and checks.get("codex", {}).get("available")
                        and checks.get("chatgpt_login", {}).get("available") and checks.get("app_server", {}).get("available"))
    return checks
