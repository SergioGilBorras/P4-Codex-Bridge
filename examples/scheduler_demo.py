"""Seed a short-lived, fake-only queue for human CLI inspection."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from p4_codex_bridge.scheduler import ResourceScheduler, RuntimeLimits


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def event(scheduler: ResourceScheduler, row: dict, kind: str) -> None:
    data = {"type": kind, "timestamp": stamp(), "thread_id": row["thread_id"],
            "turn_id": row["turn_id"], "data": {"demo": True}}
    with scheduler._connect() as db:
        db.execute("INSERT INTO turn_events(thread_id,turn_id,event_type,timestamp,payload_json,bridge_run_id) VALUES(?,?,?,?,?,?)",
                   (row["thread_id"], row["turn_id"], kind, data["timestamp"],
                    json.dumps(data, separators=(",", ":")), row["bridge_run_id"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True,
                        help="Use this exact directory with P4_CODEX_BRIDGE_STATE_DIR in the other terminal")
    parser.add_argument("--duration", type=float, default=8, help="Seconds each fake agent remains active")
    args = parser.parse_args()
    state = args.state_dir.expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True)
    workspace = state / "demo-workspace"
    workspace.mkdir(exist_ok=True)
    other = state / "demo-workspace-other"
    other.mkdir(exist_ok=True)
    scheduler = ResourceScheduler(state / "runs.sqlite3", RuntimeLimits(global_max_active=2,
        app_server_max_active=2, exec_max_active=1, max_active_threads=4, max_queue_size=20,
        profile_limits={"analysis": 4}), instance_id="fake-demo")
    with scheduler._connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS turn_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,thread_id TEXT,turn_id TEXT,event_type TEXT NOT NULL,timestamp TEXT NOT NULL,payload_json TEXT NOT NULL,bridge_run_id TEXT)")
    now = stamp()
    definitions = [
        ("demo_write", "demo-thread-1", "app-server", workspace, "WRITE", "ImplementationAgent", "DEMO-WRITE"),
        ("demo_blocked", "demo-thread-2", "exec", workspace, "READ", "ValidationAgent", "DEMO-LOCK"),
        ("demo_exec", "demo-thread-3", "exec", other, "WRITE", "AnalysisAgent", "DEMO-EXEC"),
        ("demo_global", "demo-thread-4", "app-server", other, "READ", "ReviewAgent", "DEMO-GLOBAL"),
    ]
    for index, (run_id, thread, backend, root, mode, agent, task) in enumerate(definitions):
        if scheduler.get(run_id):
            continue
        scheduler.submit(turn_id=thread, thread_id=thread, backend=backend, profile="analysis",
            workspace=root, prompt="[FAKE DEMO PROMPT]", access_mode=mode, bridge_run_id=run_id,
            submitted_at=(datetime.fromisoformat(now) + timedelta(seconds=index)).isoformat(),
            metadata={"agent_name": agent, "task_key": task, "project": "scheduler-demo"})

    print("Fake-only scheduler demo: no Codex child and zero tokens.")
    print(f"In the other terminal set P4_CODEX_BRIDGE_STATE_DIR={state}")
    print("Commands (run separately): p4-codex ps --json; p4-codex inspect demo_write; p4-codex watch demo_write; p4-codex resources; p4-codex cancel demo_global")
    print("Runs: demo_write, demo_blocked (workspace), demo_exec, demo_global (global slots)")

    active_until: dict[str, float] = {}
    deadline = time.monotonic() + max(args.duration * 3, 15)
    while time.monotonic() < deadline:
        for item in scheduler.dispatch():
            event(scheduler, item, "TURN_STARTED")
            event(scheduler, item, "AGENT_MESSAGE_COMPLETED")
            active_until[item["bridge_run_id"]] = time.monotonic() + args.duration
        now_mono = time.monotonic()
        for run_id, end in list(active_until.items()):
            if now_mono >= end:
                row = scheduler.get(run_id)
                scheduler.finish(run_id, "COMPLETED", finished_at=stamp())
                event(scheduler, row, "TURN_COMPLETED")
                del active_until[run_id]
        if not active_until and not any(row["status"] in scheduler.QUEUED for row in scheduler.list_runs()):
            break
        time.sleep(.1)
    print(json.dumps(scheduler.resources(), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
