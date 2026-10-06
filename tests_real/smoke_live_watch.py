"""Manual one-turn smoke proving a watcher can observe without controlling a run."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from p4_codex_bridge import CodexBridge, CodexRuntimeManager, TurnState


def _numeric_usage(value):
    """Keep only numeric counters from the Codex usage payload."""
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                clean[str(key)] = item
            elif isinstance(item, dict):
                nested = _numeric_usage(item)
                if nested:
                    clean[str(key)] = nested
        return clean
    return {}


def main() -> int:
    workspace = Path(__file__).resolve().parent / "smoke_workspace"
    state = Path(__file__).resolve().parent / ".live-watch-state"
    manager = CodexRuntimeManager(cwd=workspace, database_path=state / "runs.sqlite3", max_active_turns=1)
    bridge = CodexBridge(state_dir=state, allowed_roots=[workspace])
    started = time.monotonic()
    report = None
    result_code = 1
    try:
        manager.start()
        thread = manager.create_thread(profile="analysis", sandbox="read-only", approval_policy="never")
        turn = manager.start_turn(thread.thread_id, "Reply exactly: OK")
        run_id = turn.bridge_run_id
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and turn.status not in {TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED, TurnState.UNKNOWN}:
            time.sleep(0.1)
        required = {"TurnStarted", "AgentMessageDelta", "TurnCompleted"}
        journal_deadline = time.monotonic() + 5
        observed = []
        event_types = []
        while time.monotonic() < journal_deadline:
            observed = list(bridge.watch(run_id))
            event_types = [item.get("type") for item in observed]
            if required.issubset(set(event_types)):
                break
            time.sleep(0.05)
        usage_events = [event.get("data", {}).get("tokenUsage") for event in turn.events
                        if event.get("type") == "TokenUsageUpdated" and isinstance(event.get("data"), dict)]
        usage = _numeric_usage(usage_events[-1]) if usage_events else None
        inspected = bridge.inspect(run_id)
        resources = manager.get_resource_status()
        health_before_shutdown = manager.health()["status"]
        watcher_preserved_status = turn.status == TurnState.COMPLETED
        report = {"bridge_run_id": run_id, "thread_id": thread.thread_id, "turn_id": turn.turn_id,
                  "model": turn.model, "events": event_types, "final_text": turn.final_text,
                  "turn_status": turn.status.value, "inspect_status": inspected.get("status"),
                  "watch_read_only": watcher_preserved_status,
                  "latency_ms": round((time.monotonic() - started) * 1000), "token_usage": usage,
                  "queue_length": len(resources.get("queued_runs", [])),
                  "workspace_locks": len(resources.get("workspace_locks", [])),
                  "health_before_shutdown": health_before_shutdown}
        result_code = 0 if (required.issubset(set(event_types)) and turn.final_text.strip() == "OK"
                            and turn.status == TurnState.COMPLETED and inspected.get("status") == "COMPLETED"
                            and watcher_preserved_status and not resources.get("queued_runs")
                            and not resources.get("workspace_locks")) else 1
    finally:
        manager.stop(mode="WAIT")
    if report is not None:
        report["health_after_shutdown"] = manager.health()["status"]
        print(json.dumps(report, ensure_ascii=False))
        if report["health_after_shutdown"] != "STOPPED":
            result_code = 1
    return result_code


if __name__ == "__main__": raise SystemExit(main())
