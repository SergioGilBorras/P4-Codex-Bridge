"""Manual resident-manager approval smoke; never run by automated tests."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from portable_tempdirs import temporary_directory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from p4_codex_bridge import CodexBridge, CodexRuntimeManager, TurnState
from p4_codex_bridge.runtime import probe


def _usage(turn):
    for event in reversed(turn.events):
        if event.get("type") == "TokenUsageUpdated" and isinstance(event.get("data"), dict):
            return event["data"].get("tokenUsage", event["data"])
    return None


def main() -> int:
    workspace = (ROOT / "tests_real" / "approval_workspace").resolve(strict=True)
    target = (workspace / "p4-runtime-approval-probe.txt").resolve()
    if target.parent != workspace or target.exists():
        print(json.dumps({"error": "Refusing to run: target must be absent inside approval_workspace"}))
        return 2
    if "Logged in using ChatGPT" not in probe(["login", "status"], timeout=15):
        print(json.dumps({"auth_available": False, "error": "Codex ChatGPT login is unavailable"}))
        return 2
    started = time.monotonic()
    # Keep runtime SQLite outside the IDE-indexed approval fixture. Only the
    # requested Codex file operation belongs in that workspace.
    with temporary_directory("P4ApprovalState") as state_dir:
        manager = CodexRuntimeManager(cwd=workspace, database_path=Path(state_dir) / "runs.sqlite3",
            lock_path=Path(state_dir) / "runs.lock", approval_timeout_seconds=90)
        approval_id = None
        saw_waiting_approval = False
        turn = None
        approval_status = None
        try:
            manager.start()
            # A read-only sandbox makes the requested single file write require an explicit decision.
            thread = manager.create_thread(profile="analysis", cwd=workspace, sandbox="read-only", approval_policy="on-request")
            turn = manager.start_turn(thread.thread_id,
                "Create exactly one file named p4-runtime-approval-probe.txt in the current directory containing P4_APPROVAL_PROBE. Do not run commands or touch any other path.",
                timeout=120, access_mode="WRITE")
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and turn.status not in {TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED, TurnState.UNKNOWN}:
                pending = manager.list_pending_approvals()
                if pending:
                    approval_id = pending[0]["approval_id"]
                    saw_waiting_approval = turn.status == TurnState.WAITING_APPROVAL
                    manager.reject(approval_id)
                    break
                time.sleep(.1)
            while time.monotonic() < deadline and turn.status not in {TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED, TurnState.UNKNOWN}:
                time.sleep(.1)
            if approval_id:
                approval_status = manager.get_approval(approval_id)["status"]
            if turn:
                observer = CodexBridge(state_dir=state_dir)
                persisted_events = list(observer.watch(turn.bridge_run_id))
            else:
                persisted_events = []
            result = {"approval_id": approval_id, "waiting_approval_observed": saw_waiting_approval,
                "turn_status": turn.status.value, "target_created_before_cleanup": target.exists(),
                "latency_ms": round((time.monotonic()-started)*1000),
                "approval_status_after_decision": approval_status,
                "final_text": turn.final_text.strip()[:160] if not approval_id else None,
                "approval_event_observed": any(event.get("type") == "ApprovalRequested" for event in persisted_events),
                "decision": "reject" if approval_id else "no approval observed", "token_usage": _usage(turn)}
        finally:
            manager.stop(mode="WAIT")
            # Delete only this script's known probe file, and only if it resolves directly in the fixture.
            if target.parent == workspace and target.is_file():
                target.unlink()
        result["health_after_shutdown"] = manager.health()["status"]
    result["state_dir_removed"] = not Path(state_dir).exists()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if approval_id and saw_waiting_approval and approval_status == "RESOLVED" and result["health_after_shutdown"] == "STOPPED" and result["state_dir_removed"] and not target.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
