from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import BridgeRun, RunStatus, utc_now
from .runtime import redact_structured


class RunRegistry:
    """Small SQLite metadata registry; prompts, output and credentials are not stored."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            # Serialize schema discovery and ALTER TABLE across worker, CLI and
            # runtime-manager processes sharing a newly created state database.
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                bridge_run_id TEXT PRIMARY KEY,
                pid INTEGER,
                worker_pid INTEGER,
                pid_identity TEXT,
                worker_identity TEXT,
                result_path TEXT,
                backend TEXT NOT NULL,
                cwd TEXT NOT NULL,
                model TEXT,
                profile TEXT NOT NULL,
                started_at TEXT NOT NULL,
                status TEXT NOT NULL,
                exit_code INTEGER,
                last_error TEXT
            )""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
            if "result_path" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN result_path TEXT")
                columns.add("result_path")
            for name, definition in {
                "server_id": "TEXT", "session_id": "TEXT", "thread_id": "TEXT", "turn_id": "TEXT",
                "agent_metadata_json": "TEXT NOT NULL DEFAULT '{}'", "permissions_json": "TEXT", "config_policy": "TEXT",
                "security_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
                    columns.add(name)
            db.execute("""CREATE TABLE IF NOT EXISTS turn_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT,
                turn_id TEXT,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_turn_events_thread_sequence ON turn_events(thread_id, sequence)")
            event_columns = {row[1] for row in db.execute("PRAGMA table_info(turn_events)")}
            if "bridge_run_id" not in event_columns: db.execute("ALTER TABLE turn_events ADD COLUMN bridge_run_id TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS idx_turn_events_run_sequence ON turn_events(bridge_run_id, sequence)")
            db.execute("""CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                thread_id TEXT,
                turn_id TEXT,
                status TEXT NOT NULL,
                method TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                payload_json TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS runtime_approvals(
                approval_id TEXT PRIMARY KEY,server_id TEXT NOT NULL,bridge_run_id TEXT,thread_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,method TEXT NOT NULL,status TEXT NOT NULL,decision TEXT,created_at TEXT NOT NULL,
                resolved_at TEXT,payload_json TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS runtime_servers(instance_id TEXT PRIMARY KEY,pid INTEGER,command_fingerprint TEXT NOT NULL,started_at TEXT NOT NULL,status TEXT NOT NULL,last_error TEXT)""")

    def add_turn_event(self, event: Any) -> None:
        """Persist lifecycle events only; message deltas and tool payloads remain transient."""
        event_type = getattr(event, "type", None)
        if event_type not in {"ThreadStarted", "ThreadResumed", "ThreadForked", "TurnReconciled", "TurnStarted", "AgentMessageDelta", "AgentMessageCompleted", "ToolStarted", "ToolCompleted", "ApprovalRequested", "ApprovalResolved", "TurnCompleted", "TurnFailed", "TurnInterrupted", "TurnStopped", "ServerError"}:
            return
        payload = json.dumps(redact_structured(event.to_dict()), ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 64 * 1024:
            payload = json.dumps({"type": event_type, "timestamp": getattr(event, "timestamp", utc_now()), "truncated": True}, separators=(",", ":"))
        with self._connect() as db:
            run = db.execute("SELECT bridge_run_id FROM runs WHERE turn_id=? LIMIT 1", (event.turn_id,)).fetchone() if event.turn_id else None
            db.execute("INSERT INTO turn_events(thread_id,turn_id,event_type,timestamp,payload_json,bridge_run_id) VALUES(?,?,?,?,?,?)",
                       (event.thread_id, event.turn_id, event_type, event.timestamp, payload, run[0] if run else None))

    def list_turn_events(self, *, thread_id: str | None = None, turn_id: str | None = None, after_sequence: int = 0,
                         include_activity: bool = False) -> list[dict[str, Any]]:
        clauses = ["sequence > ?"]
        params: list[Any] = [after_sequence]
        if not include_activity:
            clauses.append("event_type IN ('ThreadStarted','ThreadResumed','ThreadForked','TurnReconciled','TurnStarted','ApprovalRequested','ApprovalResolved','TurnCompleted','TurnFailed','TurnInterrupted','TurnStopped','ServerError','SUBMITTED','QUEUED','WAITING_FOR_SLOT','RUNNING','RESOURCE_BLOCKED','RESOURCE_ACQUIRED','RESOURCE_RELEASED','CANCELLED','FAILED')")
        if thread_id:
            clauses.append("thread_id = ?"); params.append(thread_id)
        if turn_id:
            clauses.append("turn_id = ?"); params.append(turn_id)
        with self._connect() as db:
            rows = db.execute(f"SELECT sequence,payload_json FROM turn_events WHERE {' AND '.join(clauses)} ORDER BY sequence", params).fetchall()
        return [{**json.loads(row["payload_json"]), "persistence_sequence": row["sequence"]} for row in rows]

    def list_turn_states(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("""SELECT sequence,thread_id,turn_id,event_type,payload_json FROM turn_events
                WHERE turn_id IS NOT NULL AND event_type IN ('ThreadStarted','ThreadResumed','ThreadForked','TurnReconciled','TurnStarted','ApprovalRequested','ApprovalResolved','TurnCompleted','TurnFailed','TurnInterrupted','TurnStopped','ServerError')
                ORDER BY sequence""").fetchall()
            approvals = db.execute("SELECT turn_id,approval_id,status FROM approvals WHERE status IN ('PENDING','DECISION')").fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            latest[row["turn_id"]] = {"thread_id": row["thread_id"], "turn_id": row["turn_id"], "event_type": row["event_type"], "sequence": row["sequence"], "data": payload.get("data", {})}
        pending = {row["turn_id"] for row in approvals}
        result = []
        for turn_id, row in latest.items():
            if turn_id in pending:
                status = "WAITING_APPROVAL"
            else:
                status = {"TurnStarted": "RUNNING", "ApprovalResolved": "RUNNING", "TurnCompleted": "COMPLETED", "TurnFailed": "FAILED", "TurnInterrupted": "INTERRUPTED", "TurnStopped": "STOPPED", "ServerError": "FAILED"}.get(row["event_type"], "UNKNOWN")
            result.append({**row, "status": status})
        return sorted(result, key=lambda item: item["sequence"], reverse=True)

    def upsert_approval(self, approval: Any, *, status: str, decision: str | None = None) -> None:
        payload = approval.__dict__ if hasattr(approval, "__dict__") else approval
        with self._connect() as db:
            db.execute("""INSERT INTO approvals(approval_id,thread_id,turn_id,status,method,created_at,resolved_at,payload_json)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(approval_id) DO UPDATE SET status=excluded.status,resolved_at=excluded.resolved_at,payload_json=excluded.payload_json""",
                (str(payload.get("approval_id")), payload.get("thread_id"), payload.get("turn_id"), status, payload.get("method", ""),
                 payload.get("created_at", utc_now()), utc_now() if status != "PENDING" else None,
                 json.dumps({**payload, "decision": decision}, ensure_ascii=False, separators=(",", ":"))))

    def list_approvals(self, *, pending_only: bool = True) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM approvals WHERE status='PENDING' ORDER BY created_at" if pending_only else "SELECT * FROM approvals ORDER BY created_at").fetchall()
        return [{**json.loads(row["payload_json"]), **dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def list_runtime_approvals(self, *, pending_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE status='PENDING'" if pending_only else ""
        with self._connect() as db:
            rows = db.execute(f"SELECT * FROM runtime_approvals {where} ORDER BY created_at").fetchall()
        return [{**json.loads(row["payload_json"]), **dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def submit_runtime_approval_decision(self, approval_id: str, decision: str) -> None:
        if decision not in {"accept", "decline"}:
            raise ValueError("decision must be accept or decline")
        with self._connect() as db:
            row = db.execute("""SELECT a.server_id FROM runtime_approvals a JOIN runtime_servers s ON s.instance_id=a.server_id
                WHERE a.approval_id=? AND a.status='PENDING' AND s.status='HEALTHY'""", (str(approval_id),)).fetchone()
            if row is None:
                raise KeyError("pending approval not owned by a live runtime instance")
            db.execute("UPDATE runtime_approvals SET status='DECISION',decision=? WHERE approval_id=? AND status='PENDING'", (decision, str(approval_id)))

    def submit_approval_decision(self, approval_id: str, decision: str) -> None:
        if decision not in {"accept", "decline", "cancel"}:
            raise ValueError("decision must be accept, decline or cancel")
        with self._connect() as db:
            row = db.execute("SELECT payload_json FROM approvals WHERE approval_id=? AND status='PENDING'", (str(approval_id),)).fetchone()
            if row is None:
                raise KeyError("pending approval not found or already resolved")
            payload = json.loads(row["payload_json"]); payload["decision"] = decision
            db.execute("UPDATE approvals SET status='DECISION',payload_json=? WHERE approval_id=? AND status='PENDING'", (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), str(approval_id)))

    def pending_approval_decisions(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM approvals WHERE status='DECISION'").fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def create(self, run_id: str, *, backend: str, cwd: str, model: str | None, profile: str, result_path: str,
               agent_metadata: dict[str, Any] | None = None, permissions: dict[str, Any] | None = None,
               config_policy: str | None = None, security_snapshot: dict[str, Any] | None = None) -> None:
        metadata = _clean_metadata(agent_metadata or {})
        with self._connect() as db:
            db.execute(
                "INSERT INTO runs(bridge_run_id,backend,cwd,model,profile,started_at,status,result_path,agent_metadata_json,permissions_json,config_policy,security_snapshot_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, backend, cwd, model, profile, utc_now(), RunStatus.STARTING.value, result_path,
                 json.dumps(metadata, ensure_ascii=False), json.dumps(redact_structured(permissions), ensure_ascii=False) if permissions else None, config_policy,
                 json.dumps(redact_structured(security_snapshot or {}), ensure_ascii=False)),
            )

    def update(self, run_id: str, **fields: Any) -> None:
        allowed = {"pid", "worker_pid", "pid_identity", "worker_identity", "status", "exit_code", "last_error",
                   "server_id", "session_id", "thread_id", "turn_id"}
        if not fields or fields.keys() - allowed:
            raise ValueError("invalid registry fields")
        assignments = ",".join(f"{key}=?" for key in fields)
        with self._connect() as db:
            db.execute(f"UPDATE runs SET {assignments} WHERE bridge_run_id=?", (*fields.values(), run_id))

    def get(self, run_id: str) -> BridgeRun | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE bridge_run_id=?", (run_id,)).fetchone()
        return BridgeRun.from_row(row) if row else None

    def raw(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE bridge_run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list(self) -> list[BridgeRun]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()
        return [BridgeRun.from_row(row) for row in rows]

    def discover(self, *, active: bool = False, task: str | None = None, agent: str | None = None,
                 backend: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "runtime_turns" in tables:
                columns = {row[1] for row in db.execute("PRAGMA table_info(runtime_turns)")}
                if "bridge_run_id" in columns:
                    rows.extend(dict(row) for row in db.execute("""SELECT t.turn_id,t.bridge_run_id,t.thread_id,t.status,t.started_at,t.finished_at,t.model,t.error,t.final_text,
                        r.cwd,r.profile,r.permissions_json,r.config_policy,t.agent_metadata_json,r.server_id,s.pid,s.command_fingerprint,'app-server' AS backend
                        FROM runtime_turns t LEFT JOIN runtime_threads r ON r.thread_id=t.thread_id LEFT JOIN runtime_servers s ON s.instance_id=r.server_id ORDER BY t.started_at DESC""").fetchall())
            scheduler = {}
            if "scheduler_runs" in tables:
                known_run_ids = {str(row.get("bridge_run_id") or row.get("turn_id")) for row in rows}
                runtime_join = "LEFT JOIN runtime_threads t ON t.thread_id=q.thread_id" if "runtime_threads" in tables else ""
                thread_fields = "COALESCE(NULLIF(t.agent_metadata_json,'{}'),q.agent_metadata_json,'{}') AS agent_metadata_json,t.model,t.permissions_json,t.config_policy" if "runtime_threads" in tables else "q.agent_metadata_json AS agent_metadata_json,NULL AS model,NULL AS permissions_json,NULL AS config_policy"
                for item in db.execute(f"""SELECT q.bridge_run_id,q.turn_id,q.thread_id,q.backend,q.profile,q.workspace AS cwd,q.access_mode,
                    q.status,q.submitted_at AS started_at,q.waiting_reason,q.blocked_by_run_id,
                    {thread_fields} FROM scheduler_runs q {runtime_join} ORDER BY q.submitted_at DESC"""):
                    if item["bridge_run_id"] not in known_run_ids: rows.append(dict(item))
                for item in db.execute("""SELECT bridge_run_id,workspace,access_mode,waiting_reason,blocked_by_run_id,
                    CASE WHEN status IN ('QUEUED','WAITING_FOR_SLOT') THEN (SELECT COUNT(*) FROM scheduler_runs q WHERE q.status IN ('QUEUED','WAITING_FOR_SLOT') AND (q.priority>r.priority OR (q.priority=r.priority AND (q.submitted_at<r.submitted_at OR (q.submitted_at=r.submitted_at AND q.bridge_run_id<=r.bridge_run_id))))) ELSE NULL END AS queue_position
                    FROM scheduler_runs r"""):
                    scheduler[item["bridge_run_id"]] = dict(item)
        result = []
        for row in rows:
            metadata_raw = row.get("agent_metadata_json") or "{}"
            try: metadata = _clean_metadata(json.loads(metadata_raw))
            except (TypeError, json.JSONDecodeError): metadata = {}
            normalized = {**row, "agent_metadata": metadata}
            normalized["bridge_run_id"] = row.get("bridge_run_id") or row.get("turn_id")
            normalized.update(scheduler.get(normalized["bridge_run_id"], {}))
            normalized["status"] = str(row.get("status", "UNKNOWN"))
            if active and normalized["status"].upper() not in {"STARTING", "SUBMITTED", "RUNNING", "WAITING_APPROVAL", "QUEUED", "WAITING_FOR_SLOT"}: continue
            if task and metadata.get("task_key") != task: continue
            if agent and metadata.get("agent_name") != agent: continue
            if backend and backend.casefold() not in str(row.get("backend", "")).casefold(): continue
            if status and normalized["status"].casefold() != status.casefold(): continue
            result.append(normalized)
        return result

    def resolve_reference(self, reference: str) -> dict[str, Any]:
        if not isinstance(reference, str) or not reference.strip(): raise ValueError("run reference is required")
        ref = reference.strip()
        matches = [row for row in self.discover() if ref in {str(row.get("bridge_run_id")), str(row.get("session_id")), str(row.get("thread_id")), str(row.get("turn_id"))}]
        # The native IDs may resolve several turns; return the whole candidate set for explicit ambiguity handling.
        unique = {str(row.get("bridge_run_id")): row for row in matches}
        if not unique: raise KeyError(f"no managed run found for reference: {ref}")
        if len(unique) > 1: raise ValueError(f"ambiguous run reference {ref}: {', '.join(unique)}")
        row = next(iter(unique.values()))
        return {"bridge_run_id": row.get("bridge_run_id"), "matched_reference": ref, "backend": row.get("backend"), "run": row}

    def inspect(self, reference: str) -> dict[str, Any]:
        resolved = self.resolve_reference(reference)
        row = resolved["run"]
        metadata = row.get("agent_metadata", {})
        started = row.get("started_at")
        try:
            from datetime import datetime, timezone
            elapsed = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()) if started else None
        except (TypeError, ValueError): elapsed = None
        events = self.events_for(row)
        usage = next((item.get("data", {}).get("usage") or item.get("data", {}).get("tokenUsage") for item in reversed(events)
                      if isinstance(item.get("data"), dict) and (item.get("data", {}).get("usage") or item.get("data", {}).get("tokenUsage"))), None)
        result = {key: row.get(key) for key in ("bridge_run_id", "backend", "pid", "pid_identity", "server_id", "session_id", "thread_id", "turn_id", "cwd", "model", "profile", "permissions_json", "config_policy", "status", "started_at", "last_error", "error")}
        result.update({"elapsed_seconds": elapsed, "token_usage": redact_structured(usage) if usage is not None else None, "pending_approval": None, "last_event": events[-1] if events else None,
                       "agent_name": metadata.get("agent_name"), "agent_role": metadata.get("agent_role"), "task_key": metadata.get("task_key"), "project": metadata.get("project"),
                       "agent_metadata": metadata, "event_replay_complete": False})
        with self._connect() as db:
            tables = {item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "runtime_threads" in tables and row.get("thread_id"):
                thread = db.execute("""SELECT t.parent_thread_id,t.server_id,t.status,t.resumable,t.remote_state_verified,t.replay_complete,t.ephemeral,s.status AS server_status
                    FROM runtime_threads t LEFT JOIN runtime_servers s ON s.instance_id=t.server_id WHERE t.thread_id=?""", (row["thread_id"],)).fetchone()
                if thread:
                    result.update({"parent_thread_id": thread["parent_thread_id"], "recovered": thread["server_status"] != "HEALTHY",
                                   "remote_state_verified": bool(thread["remote_state_verified"]) and thread["server_status"] == "HEALTHY", "resumable": bool(thread["resumable"]),
                                   "ephemeral": bool(thread["ephemeral"]), "event_replay_complete": bool(thread["replay_complete"])})
            if "runtime_approvals" in tables and row.get("turn_id"):
                approval = db.execute("SELECT approval_id,status,server_id FROM runtime_approvals WHERE turn_id=? AND status IN ('PENDING','DECISION') ORDER BY created_at LIMIT 1", (row["turn_id"],)).fetchone()
                if approval:
                    result["pending_approval"] = {"approval_id": approval["approval_id"], "status": approval["status"], "server_id": approval["server_id"]}
            if "scheduler_runs" in tables:
                scheduled = db.execute("SELECT workspace,access_mode,status,waiting_reason,blocked_by_run_id,priority,submitted_at FROM scheduler_runs WHERE bridge_run_id=?", (row.get("bridge_run_id"),)).fetchone()
                if scheduled:
                    result.update(dict(scheduled))
                    result["queue_position"] = next((item.get("queue_position") for item in self.discover() if item.get("bridge_run_id") == row.get("bridge_run_id")), None)
                    result["slot_state"] = {"global": "see resources", "backend": row.get("backend"), "profile": row.get("profile")}
        result["native_session_id"] = row.get("session_id") or row.get("thread_id")
        raw_permissions = row.get("permissions_json")
        try: result["permissions"] = json.loads(raw_permissions) if raw_permissions else None
        except (TypeError, json.JSONDecodeError): result["permissions"] = None
        result.pop("permissions_json", None)
        result["process_identity"] = row.get("pid_identity") or row.get("command_fingerprint")
        result["pending_approval"] = None
        if row.get("turn_id"):
            with self._connect() as db:
                tables = {item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "approvals" in tables:
                    approval = db.execute("SELECT payload_json FROM approvals WHERE turn_id=? AND status='PENDING' ORDER BY created_at LIMIT 1", (row["turn_id"],)).fetchone()
                    if approval:
                        try: result["pending_approval"] = redact_structured(json.loads(approval[0]))
                        except (TypeError, json.JSONDecodeError): pass
        return result

    def update_by_turn(self, turn_id: str, *, status: str, error: str | None = None) -> None:
        with self._connect() as db:
            db.execute("UPDATE runs SET status=?,last_error=COALESCE(?,last_error) WHERE turn_id=?", (status, error, turn_id))

    def add_run_event(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        with self._connect() as db:
            row = db.execute("SELECT thread_id,turn_id FROM runs WHERE bridge_run_id=?", (run_id,)).fetchone()
            if row is None: return
            event = {"type": event_type, "timestamp": utc_now(), "thread_id": row["thread_id"], "turn_id": row["turn_id"], "data": redact_structured(data)}
            payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            if len(payload.encode("utf-8")) > 64 * 1024: payload = json.dumps({"type": event_type, "timestamp": event["timestamp"], "truncated": True}, separators=(",", ":"))
            db.execute("INSERT INTO turn_events(thread_id,turn_id,event_type,timestamp,payload_json,bridge_run_id) VALUES(?,?,?,?,?,?)",
                       (row["thread_id"], row["turn_id"], event_type, event["timestamp"], payload, run_id))

    def events_for(self, run: dict[str, Any], *, after_sequence: int = 0) -> list[dict[str, Any]]:
        thread_id, turn_id = run.get("thread_id"), run.get("turn_id")
        events: list[dict[str, Any]] = []
        with self._connect() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "turn_events" in tables and run.get("bridge_run_id"):
                cols = {r[1] for r in db.execute("PRAGMA table_info(turn_events)")}
                if "bridge_run_id" in cols:
                    rows = db.execute("SELECT sequence,payload_json FROM turn_events WHERE bridge_run_id=? AND sequence>? ORDER BY sequence", (run["bridge_run_id"], after_sequence)).fetchall()
                    events.extend({**json.loads(item["payload_json"]), "persistence_sequence": item["sequence"]} for item in rows)
            if not events and (thread_id or turn_id):
                events.extend(self.list_turn_events(thread_id=thread_id, turn_id=turn_id, after_sequence=after_sequence, include_activity=True))
            if "runtime_events" in tables and turn_id:
                rows = db.execute("SELECT sequence,payload_json FROM runtime_events WHERE turn_id=? AND sequence>? ORDER BY sequence", (turn_id, after_sequence)).fetchall()
                events.extend({**json.loads(row["payload_json"]), "persistence_sequence": row["sequence"]} for row in rows)
        ordered = sorted(events, key=lambda item: (item.get("timestamp", ""), item.get("persistence_sequence", 0)))
        deduplicated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for event in ordered:
            content = {key: value for key, value in event.items() if key != "persistence_sequence"}
            identity = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if identity in seen:
                continue
            seen.add(identity)
            deduplicated.append(event)
        return deduplicated


def _clean_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict): raise ValueError("agent metadata must be a JSON object")
    cleaned = redact_structured(value)
    def omit_prompts(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: ("[OMITTED]" if str(key).casefold() in {"prompt", "prompt_text", "full_prompt", "input_text"} else omit_prompts(val)) for key, val in item.items()}
        if isinstance(item, list): return [omit_prompts(value) for value in item]
        return item
    cleaned = omit_prompts(cleaned)
    encoded = json.dumps(cleaned, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 8192: raise ValueError("agent metadata exceeds 8 KiB")
    return cleaned
