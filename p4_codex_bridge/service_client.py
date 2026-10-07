"""Typed, same-machine client for submitting work to a running bridge service."""
from __future__ import annotations

import json
import hashlib
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .permissions import CodexPermissions
from .security import RunSecurityPolicy, validate_run_security
from .service import _connect, _ensure_service_schema, default_state_dir, read_service_state
from .errors import BridgeTimeoutError, ConflictError, QueueFullError, ServiceUnavailableError

MAX_COMMAND_BYTES = 1024 * 1024
MAX_PROMPT_BYTES = 512 * 1024
MAX_METADATA_BYTES = 32 * 1024
COMMAND_TYPES = {"SUBMIT_EXEC_RUN", "CREATE_THREAD", "START_TURN"}


@dataclass(frozen=True)
class CommandResult:
    command_id: str
    command_type: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class ExecRunSubmission:
    prompt: str
    cwd: str
    profile: str = "analysis"
    model: str | None = None
    timeout_seconds: float | None = None
    config_policy: str | None = None
    metadata: dict[str, Any] | None = None
    resource_priority: int = 0
    access_mode: str = "READ"
    permissions: CodexPermissions | None = None
    output_schema: dict[str, Any] | None = None
    security_policy: RunSecurityPolicy = RunSecurityPolicy()

    def payload(self) -> dict[str, Any]:
        if not isinstance(self.prompt, str) or not self.prompt.strip() or len(self.prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ValueError("prompt is required and must not exceed 512 KiB")
        root = Path(self.cwd).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("cwd must be an absolute existing directory")
        if not isinstance(self.profile, str) or not self.profile or len(self.profile) > 64:
            raise ValueError("profile is invalid")
        if self.config_policy is not None and self.config_policy not in {"isolated", "project", "explicit"}:
            raise ValueError("config_policy must be isolated, project or explicit")
        if not isinstance(self.security_policy, RunSecurityPolicy):
            raise TypeError("security_policy must be RunSecurityPolicy")
        validate_run_security(self.security_policy, backend="exec", config_policy=self.config_policy or "isolated", cwd=root)
        if self.output_schema is not None and not isinstance(self.output_schema, dict):
            raise TypeError("output_schema must be a JSON object")
        if self.model is not None and (not isinstance(self.model, str) or len(self.model) > 128):
            raise ValueError("model is invalid")
        if self.timeout_seconds is not None and (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not 0 < self.timeout_seconds <= 3600):
            raise ValueError("timeout_seconds must be in (0, 3600]")
        if isinstance(self.resource_priority, bool) or not isinstance(self.resource_priority, int) or not -100 <= self.resource_priority <= 100:
            raise ValueError("resource_priority must be an integer from -100 to 100")
        if self.access_mode not in {"READ", "WRITE"}:
            raise ValueError("access_mode must be READ or WRITE")
        metadata = self.metadata or {}
        _validate_metadata(metadata)
        if self.permissions is not None and not isinstance(self.permissions, CodexPermissions):
            raise TypeError("permissions must be CodexPermissions")
        permissions = None
        if self.permissions:
            permissions = {"sandbox": self.permissions.sandbox.value,
                "approval_policy": self.permissions.approval_policy.value,
                "writable_roots": [str(p) for p in self.permissions.writable_roots],
                "network_access": self.permissions.network_access}
        payload = {"prompt": self.prompt, "cwd": str(root.resolve()), "profile": self.profile,
            "model": self.model, "timeout_seconds": self.timeout_seconds,
            "config_policy": self.config_policy, "metadata": metadata,
            "resource_priority": self.resource_priority, "access_mode": self.access_mode,
            "permissions": permissions, "output_schema": self.output_schema}
        payload["security_policy"] = self.security_policy.to_dict()
        _check_payload_size(payload)
        return payload


@dataclass(frozen=True)
class CreateThreadRequest:
    cwd: str
    profile: str = "analysis"
    model: str | None = None
    sandbox: str = "read-only"
    approval_policy: str = "never"
    config_policy: str = "project"
    metadata: dict[str, Any] | None = None
    security_policy: RunSecurityPolicy = RunSecurityPolicy()

    def payload(self) -> dict[str, Any]:
        root = Path(self.cwd).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("cwd must be an absolute existing directory")
        if not isinstance(self.profile, str) or not self.profile or len(self.profile) > 64:
            raise ValueError("profile is invalid")
        if self.model is not None and (not isinstance(self.model, str) or len(self.model) > 128):
            raise ValueError("model is invalid")
        if self.sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
            raise ValueError("unsupported sandbox")
        if self.approval_policy not in {"never", "on-request", "untrusted"}:
            raise ValueError("unsupported approval policy")
        if self.sandbox == "danger-full-access" and self.approval_policy != "on-request":
            raise ValueError("danger-full-access requires explicit on-request approval policy")
        if self.config_policy not in {"isolated", "project", "explicit"}:
            raise ValueError("unsupported config policy")
        if not isinstance(self.security_policy, RunSecurityPolicy):
            raise TypeError("security_policy must be RunSecurityPolicy")
        validate_run_security(self.security_policy, backend="app-server", config_policy=self.config_policy, cwd=root)
        _validate_metadata(self.metadata or {})
        payload = {**asdict(self), "cwd": str(root.resolve()), "metadata": self.metadata or {}}
        payload["security_policy"] = self.security_policy.to_dict()
        _check_payload_size(payload)
        return payload


@dataclass(frozen=True)
class StartTurnRequest:
    thread_id: str
    prompt: str
    timeout_seconds: float = 300
    metadata: dict[str, Any] | None = None
    access_mode: str = "READ"
    resource_priority: int = 0
    security_policy: RunSecurityPolicy | None = None

    def payload(self) -> dict[str, Any]:
        if not isinstance(self.thread_id, str) or not self.thread_id or len(self.thread_id) > 256:
            raise ValueError("thread_id is required")
        if not isinstance(self.prompt, str) or not self.prompt.strip() or len(self.prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ValueError("prompt is required and must not exceed 512 KiB")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not 0 < self.timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be in (0, 3600]")
        if self.access_mode not in {"READ", "WRITE"}:
            raise ValueError("access_mode must be READ or WRITE")
        if isinstance(self.resource_priority, bool) or not isinstance(self.resource_priority, int) or not -100 <= self.resource_priority <= 100:
            raise ValueError("resource_priority must be an integer from -100 to 100")
        _validate_metadata(self.metadata or {})
        if self.security_policy is not None and not isinstance(self.security_policy, RunSecurityPolicy):
            raise TypeError("security_policy must be RunSecurityPolicy")
        payload = {**asdict(self), "metadata": self.metadata or {}}
        payload["security_policy"] = self.security_policy.to_dict() if self.security_policy else None
        _check_payload_size(payload)
        return payload


def _validate_metadata(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise TypeError("metadata must be a JSON object")
    _check_payload_size(value, MAX_METADATA_BYTES, "metadata")
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must contain JSON-safe values") from exc


def _check_payload_size(value: Any, limit: int = MAX_COMMAND_BYTES, field: str = "command payload") -> None:
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON serializable") from exc
    if size > limit:
        raise ValueError(f"{field} exceeds {limit} bytes")


class CodexServiceClient:
    """Public control client. SQLite details remain encapsulated in this class."""

    def __init__(self, state_dir: str | Path | None = None, *, config_path: str | Path | None = None):
        self.config_path = Path(config_path).resolve() if config_path else None
        if state_dir is None and self.config_path:
            from .service import ServiceConfig
            state_dir = ServiceConfig.load(self.config_path).state_dir
        self.state_dir = Path(state_dir or os.environ.get("P4_CODEX_BRIDGE_STATE_DIR") or default_state_dir()).expanduser().resolve()

    def is_available(self) -> bool:
        return bool(read_service_state(self.state_dir).get("running"))

    def _submit(self, command_type: str, payload: dict[str, Any], *, idempotency_key: str | None = None) -> str:
        if command_type not in COMMAND_TYPES:
            raise ValueError("unsupported command type")
        state = read_service_state(self.state_dir)
        if not state.get("running"):
            raise ServiceUnavailableError("P4-Codex-Bridge service is not running")
        _check_payload_size(payload)
        command_id = "cmd_" + uuid.uuid4().hex
        key = idempotency_key or command_id
        if not isinstance(key, str) or not key or len(key) > 128:
            raise ValueError("idempotency_key must be 1-128 characters")
        db_path = self.state_dir / "runs.sqlite3"
        with _connect(db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute("SELECT COUNT(*) FROM bridge_runtime_commands WHERE status IN ('SUBMITTED','CLAIMED')").fetchone()[0]
            if pending >= 1000:
                raise QueueFullError("service command queue is full")
            serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            payload_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            try:
                db.execute("""INSERT INTO bridge_runtime_commands
                    (command_id,command_type,submitted_at,submitted_by,payload,idempotency_key,payload_hash,status)
                    VALUES(?,?,?,?,?,?,?,'SUBMITTED')""",
                    (command_id, command_type, datetime.now(timezone.utc).isoformat(), str(os.getpid()), serialized, key, payload_hash))
            except Exception as exc:
                if "UNIQUE" not in str(exc):
                    raise
                existing = db.execute("SELECT command_id,command_type,payload_hash FROM bridge_runtime_commands WHERE idempotency_key=?", (key,)).fetchone()
                if not existing or existing["command_type"] != command_type or existing["payload_hash"] != payload_hash:
                    raise ConflictError("idempotency key already used for a different command") from exc
                command_id = existing["command_id"]
        return command_id

    def wait_command(self, command_id: str, timeout: float = 30, *, poll_interval: float = 0.25) -> CommandResult:
        if timeout < 0 or poll_interval <= 0:
            raise ValueError("timeout must be nonnegative and poll_interval positive")
        deadline = time.monotonic() + timeout
        db_path = self.state_dir / "runs.sqlite3"
        while True:
            with _connect(db_path) as db:
                row = db.execute("SELECT command_type,status,result,error FROM bridge_runtime_commands WHERE command_id=?", (command_id,)).fetchone()
            if row is None:
                raise KeyError(command_id)
            result = json.loads(row["result"]) if row["result"] else None
            if row["status"] in {"COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}:
                return CommandResult(command_id, row["command_type"], row["status"], result, row["error"])
            if time.monotonic() >= deadline:
                return CommandResult(command_id, row["command_type"], row["status"], result, row["error"])
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))

    def submit_exec_run(self, request: ExecRunSubmission, *, idempotency_key: str | None = None,
                        timeout: float = 30) -> CommandResult:
        if not isinstance(request, ExecRunSubmission):
            raise TypeError("request must be ExecRunSubmission")
        command_id = self._submit("SUBMIT_EXEC_RUN", request.payload(), idempotency_key=idempotency_key)
        return self.wait_command(command_id, timeout)

    def create_thread(self, request: CreateThreadRequest, *, idempotency_key: str | None = None,
                      timeout: float = 30) -> CommandResult:
        if not isinstance(request, CreateThreadRequest):
            raise TypeError("request must be CreateThreadRequest")
        command_id = self._submit("CREATE_THREAD", request.payload(), idempotency_key=idempotency_key)
        return self.wait_command(command_id, timeout)

    def start_turn(self, request: StartTurnRequest, *, idempotency_key: str | None = None,
                   timeout: float = 30) -> CommandResult:
        if not isinstance(request, StartTurnRequest):
            raise TypeError("request must be StartTurnRequest")
        command_id = self._submit("START_TURN", request.payload(), idempotency_key=idempotency_key)
        return self.wait_command(command_id, timeout)

    def inspect(self, run_id: str) -> dict[str, Any]:
        from .client import CodexBridge
        return CodexBridge(state_dir=self.state_dir).inspect(run_id)

    def watch(self, run_id: str, **options: Any):
        """Read-only watch over the shared local journal; no IPC stream is opened."""
        from .client import CodexBridge
        yield from CodexBridge(state_dir=self.state_dir).watch(run_id, **options)

    async def awatch(self, run_id: str, **options: Any):
        from .client import CodexBridge
        async for event in CodexBridge(state_dir=self.state_dir).awatch(run_id, **options):
            yield event

    def cancel(self, run_id: str) -> dict[str, Any]:
        from .client import CodexBridge
        return CodexBridge(state_dir=self.state_dir).cancel(run_id).to_dict()
