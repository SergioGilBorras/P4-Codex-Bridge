"""Manual, one-turn smoke for the resident manager. Never part of test discovery."""
from __future__ import annotations

import json
import time
from pathlib import Path

from p4_codex_bridge import CodexRuntimeManager, TurnState


def main() -> int:
    cwd = Path(__file__).resolve().parent / "smoke_workspace"
    manager = CodexRuntimeManager(cwd=cwd, database_path=Path.cwd() / ".p4-codex-runtime-smoke.sqlite",
                                  max_active_turns=1)
    started = time.monotonic()
    lifecycle: list[str] = []
    try:
        initial = manager.start()
        thread = manager.create_thread(profile="analysis", sandbox="read-only", approval_policy="never")
        turn = manager.start_turn(thread.thread_id, "Reply exactly: OK")
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and turn.status not in {
            TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED, TurnState.UNKNOWN,
        }:
            lifecycle.extend(e["type"] for e in turn.events[len(lifecycle):])
            time.sleep(0.1)
        result = {
            "initial_health": initial["status"], "final_health": manager.health()["status"],
            "thread_id": thread.thread_id, "turn_id": turn.turn_id, "turn_status": turn.status.value,
            "final_text": turn.final_text, "lifecycle": lifecycle, "latency_ms": round((time.monotonic() - started) * 1000),
            "token_usage": None, "metrics": manager.get_metrics(),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0 if turn.status == TurnState.COMPLETED and turn.final_text.strip() == "OK" else 1
    finally:
        manager.stop(mode="WAIT")


if __name__ == "__main__":
    raise SystemExit(main())
