from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class SandboxMode(StrEnum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    FULL_ACCESS = "danger-full-access"


class ApprovalPolicy(StrEnum):
    NEVER = "never"
    ON_REQUEST = "on-request"


class AppServerApprovalPolicy(StrEnum):
    NEVER = "never"
    ON_REQUEST = "on-request"
    UNTRUSTED = "untrusted"


class ConfigPolicy(StrEnum):
    ISOLATED = "isolated"
    PROJECT = "project"
    EXPLICIT = "explicit"


class ReasoningSummary(StrEnum):
    AUTO = "auto"
    CONCISE = "concise"
    DETAILED = "detailed"
    NONE = "none"


class ModelVerbosity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalHandlingPolicy(StrEnum):
    MANUAL = "manual"
    AUTO_REJECT = "auto-reject"
    NEVER_EXPECT_APPROVAL = "never-expect-approval"


class RunStatus(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    QUEUED = "QUEUED"
    WAITING_FOR_SLOT = "WAITING_FOR_SLOT"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    STOPPED = "STOPPED"
    TIMED_OUT = "TIMED_OUT"
    ORPHANED = "ORPHANED"
    LOST = "LOST"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class BridgeRun:
    bridge_run_id: str
    pid: int | None
    worker_pid: int | None
    backend: str
    cwd: str
    model: str | None
    profile: str
    started_at: str
    status: RunStatus
    exit_code: int | None = None
    last_error: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> "BridgeRun":
        data = dict(row)
        data["status"] = RunStatus(data["status"])
        return cls(**{key: data[key] for key in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass(frozen=True)
class RunResult:
    ok: bool
    bridge_run_id: str
    exit_code: int | None
    content: str
    stderr: str
    structured_output: Any = None
    error: dict[str, str] | None = None
    duration_ms: int = 0
    session_id: str | None = None
    raw_output: str | None = None

    @property
    def text_output(self) -> str:
        """Alias emphasizing that ``content`` is the assistant's final text."""
        return self.content


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
