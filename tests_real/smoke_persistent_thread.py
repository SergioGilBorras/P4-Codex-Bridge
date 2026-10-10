"""Manual three-turn persistent app-server resume/fork smoke. Never run by default."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from portable_tempdirs import temporary_directory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from p4_codex_bridge import CodexRuntimeManager, TurnState
from p4_codex_bridge.runtime import probe


def _usage(turn):
    for event in reversed(turn.events):
        if event.get("type") == "TokenUsageUpdated":
            data = event.get("data", {})
            if isinstance(data, dict):
                return data.get("tokenUsage", data)
    return None


def _wait(turn, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and turn.status not in {TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED, TurnState.UNKNOWN}:
        time.sleep(.1)
    return turn.status == TurnState.COMPLETED


def main() -> int:
    workspace = (ROOT / "tests_real" / "smoke_workspace").resolve(strict=True)
    if "Logged in using ChatGPT" not in probe(["login", "status"], timeout=15):
        print(json.dumps({"auth_available": False, "error": "Codex ChatGPT login is unavailable"}))
        return 2
    started = time.monotonic()
    with temporary_directory("P4CodexPersistentSmoke") as state_dir:
        state = Path(state_dir)
        manager = CodexRuntimeManager(cwd=workspace, database_path=state / "runs.sqlite3", max_active_turns=1)
        report = {"cli_version": probe(["--version"], timeout=10).strip(), "workspace": str(workspace),
                  "turns": [], "no_file_changes_intended": True}
        try:
            manager.start()
            original = manager.create_thread(profile="analysis", sandbox="read-only", approval_policy="never")
            report["original_thread_id"] = original.thread_id

            def do_turn(thread_id: str, prompt: str, expected: str, label: str) -> bool:
                before = time.monotonic()
                turn = manager.start_turn(thread_id, prompt)
                ok = _wait(turn)
                report["turns"].append({"label": label, "thread_id": thread_id, "turn_id": turn.turn_id,
                    "status": turn.status.value, "final_text": turn.final_text.strip(),
                    "latency_ms": round((time.monotonic() - before) * 1000), "token_usage": _usage(turn)})
                return ok and turn.final_text.strip() == expected

            first_ok = do_turn(original.thread_id, "Remember marker A. Reply exactly: A", "A", "initial")
            if not first_ok:
                report["second_stage_started"] = False
                return_code = 1
            else:
                return_code = 0

            if return_code == 0:
                resumed = manager.resume_thread(original.thread_id)
                report["resumed_thread_id"] = resumed.thread_id
                report["resume_verified"] = resumed.remote_state_verified
                report["replay_complete"] = resumed.replay_complete
                second_ok = do_turn(resumed.thread_id, "Reply with the remembered marker only.", "A", "continued_after_resume")
                if not second_ok:
                    report["fork_started"] = False
                    return_code = 1

            if return_code == 0:
                forked = manager.fork_thread(resumed.thread_id)
                report["forked_thread_id"] = forked.thread_id
                report["parent_thread_id"] = forked.parent_thread_id
                third_ok = do_turn(forked.thread_id, "Reply with the remembered marker only.", "A", "continued_on_fork")
                if not third_ok or resumed.thread_id != original.thread_id or forked.thread_id == original.thread_id:
                    return_code = 1
            report["latency_ms"] = round((time.monotonic() - started) * 1000)
            report["health_before_shutdown"] = manager.health()["status"]
        finally:
            manager.stop(mode="WAIT")
        report["health_after_shutdown"] = manager.health()["status"]
    report["state_dir_removed"] = not Path(state_dir).exists()
    print(json.dumps(report, ensure_ascii=False))
    return return_code if report["health_after_shutdown"] == "STOPPED" and report["state_dir_removed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
