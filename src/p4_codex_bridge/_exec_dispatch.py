"""Internal atomic launcher for scheduler-managed exec runs."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._worker import _identity
from .registry import RunRegistry
from .runtime import codex_environment, redact
from .scheduler import ResourceScheduler


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(registry: RunRegistry, run_id: str, event_type: str, data: dict[str, Any]) -> None:
    registry.add_run_event(run_id, event_type, data)


def dispatch(database: str | Path) -> list[str]:
    db_path = Path(database).resolve()
    state_dir = db_path.parent
    registry = RunRegistry(db_path)
    scheduler = ResourceScheduler(db_path)
    launched: list[str] = []
    while True:
        before = {row["bridge_run_id"]: row for row in scheduler.list_runs() if row["backend"] == "exec"}
        claimed = scheduler.dispatch(backend="exec")
        if not claimed: break
        for run_id, previous in before.items():
            current = scheduler.get(run_id)
            if current and current["status"] == "WAITING_FOR_SLOT" and (previous["status"] != current["status"] or previous.get("waiting_reason") != current.get("waiting_reason")):
                _event(registry, run_id, "WAITING_FOR_SLOT", {"waiting_reason": current.get("waiting_reason"), "blocked_by_run_id": current.get("blocked_by_run_id"), "queue_position": current.get("queue_position")})
                _event(registry, run_id, "RESOURCE_BLOCKED", {"waiting_reason": current.get("waiting_reason"), "blocked_by_run_id": current.get("blocked_by_run_id")})
        successful_in_batch = False
        for item in claimed:
            run_id = item["bridge_run_id"]
            row = registry.raw(run_id)
            if not row:
                scheduler.finish(run_id, "LOST", finished_at=_now(), error="exec registry row missing after scheduler claim")
                continue
            if item.get("cancel_requested"):
                scheduler.finish(run_id, "CANCELLED", finished_at=_now(), error="cancelled before worker launch")
                registry.update(run_id, status="CANCELLED", last_error="Cancelled before execution started")
                _event(registry, run_id, "CANCELLED", {})
                continue
            request = dict(item["payload"])
            request.update({"state_dir": str(state_dir), "result_path": row["result_path"],
                            "stop_path": str(state_dir / "control" / f"{run_id}.stop"),
                            "cancel_path": str(state_dir / "control" / f"{run_id}.cancel"),
                            "managed_scheduled": True})
            command = [sys.executable, "-m", "p4_codex_bridge._worker", "--db", str(db_path), "--run-id", run_id]
            package_root = str(Path(__file__).resolve().parent.parent)
            env = codex_environment()
            env["PYTHONPATH"] = os.pathsep.join(filter(None, (package_root, env.get("PYTHONPATH", ""))))
            kwargs: dict[str, Any] = {"args": command, "cwd": package_root, "env": env,
                "stdin": subprocess.PIPE, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                "shell": False, "text": True, "encoding": "utf-8"}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kwargs["startupinfo"] = startup
            else:
                kwargs["start_new_session"] = True
            worker = None
            try:
                worker = subprocess.Popen(**kwargs)
                identity = _identity(worker.pid)
                registry.update(run_id, worker_pid=worker.pid, worker_identity=identity, status="RUNNING")
                scheduler.set_process(run_id, worker_pid=worker.pid, worker_identity=identity)
                _event(registry, run_id, "RUNNING", {"backend": "exec", "worker_pid": worker.pid})
                _event(registry, run_id, "RESOURCE_ACQUIRED", {"workspace": item["workspace"], "access_mode": item["access_mode"]})
                assert worker.stdin is not None
                worker.stdin.write(json.dumps(request, ensure_ascii=False))
                worker.stdin.close()
                if os.name == "nt":
                    worker._handle.Close()
                    worker.returncode = 0
                launched.append(run_id)
                successful_in_batch = True
            except Exception as exc:
                try:
                    if worker is not None and worker.poll() is None: worker.kill(); worker.wait(timeout=2)
                except Exception: pass
                message = redact(str(exc))[:300]
                scheduler.finish(run_id, "FAILED", finished_at=_now(), error=message)
                registry.update(run_id, status="FAILED", last_error="Managed exec worker could not be started")
                _event(registry, run_id, "FAILED", {"error": "Managed exec worker could not be started"})
        if not successful_in_batch:
            # All claims were cancelled or failed to spawn; try the next eligible records.
            continue
    return launched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    dispatch(args.database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
