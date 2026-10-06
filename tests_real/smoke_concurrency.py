"""Manual two-turn Codex concurrency smoke. Never run in automated tests."""
from __future__ import annotations

import time
from p4_codex_bridge.runtime_manager import TurnState

from p4_codex_bridge.runtime_manager import CodexRuntimeManager


def main() -> None:
    manager = CodexRuntimeManager(cwd=".", max_active_turns=2)
    started = time.monotonic()
    try:
        manager.start()
        thread_a = manager.create_thread(profile="analysis")
        thread_b = manager.create_thread(profile="analysis")
        turn_a = manager.start_turn(thread_a.thread_id, "Reply exactly: A")
        turn_b = manager.start_turn(thread_b.thread_id, "Reply exactly: B")
        print({"runs": [turn_a.bridge_run_id, turn_b.bridge_run_id], "resources": manager.get_resource_status()})
        deadline = time.monotonic() + 120
        while any(turn.status not in {TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED} for turn in (turn_a, turn_b)) and time.monotonic() < deadline:
            time.sleep(.1)
        print({"elapsed_seconds": time.monotonic() - started, "results": [turn_a.final_text, turn_b.final_text]})
    finally:
        manager.stop(mode="WAIT")


if __name__ == "__main__": main()
