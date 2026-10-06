"""Manual approval-flow smoke. Never run in the automated suite."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from p4_codex_bridge import ApprovalPolicy, CodexBridge, CodexPermissions, SandboxMode
from p4_codex_bridge.runtime import probe


def main() -> int:
    workspace = (ROOT / "tests_real" / "approval_workspace").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    target = workspace / "p4-approval-probe.txt"
    if target.exists():
        raise SystemExit("Refusing to run: expected test file already exists in approval_workspace")
    if "Logged in using ChatGPT" not in probe(["login", "status"], timeout=15):
        print(json.dumps({"auth_available": False, "error": "Codex ChatGPT login is unavailable"}))
        return 2
    bridge = CodexBridge(allowed_roots=(workspace,))
    turn = bridge.start_turn(
        "Create a file named p4-approval-probe.txt in the current directory with the text P4_APPROVAL_TEST. Do not create or modify any other path.",
        cwd=workspace,
        permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.ON_REQUEST),
        approval_timeout_seconds=60,
    )
    requested = False
    rejected = False
    observed: list[str] = []
    started = time.monotonic()
    try:
        for event in turn.events(timeout=90):
            observed.append(event.type)
            if event.type == "ApprovalRequested":
                requested = True
                approval_id = event.data["approval"]["approval_id"]
                bridge.reject(approval_id)
                rejected = True
            if event.type in {"TurnCompleted", "TurnFailed", "TurnInterrupted"}:
                break
    finally:
        turn.close()
    safe = not target.exists()
    result = {"approval_requested": requested, "rejected": rejected, "turn_status": bridge.get_turn_status(turn.turn_id), "events": observed, "target_created": not safe, "latency_ms": int((time.monotonic()-started)*1000)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if requested and rejected and safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
