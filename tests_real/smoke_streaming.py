"""Manual one-turn app-server streaming smoke. Excluded from automated tests."""
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
    workspace = ROOT / "tests_real" / "smoke_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    auth = "Logged in using ChatGPT" in probe(["login", "status"], timeout=15)
    if not auth:
        print(json.dumps({"auth_available": False, "error": "Codex ChatGPT login is unavailable"}))
        return 2
    bridge = CodexBridge(allowed_roots=(workspace,))
    started = time.monotonic()
    observed: list[str] = []
    final_text = ""
    usage = None
    try:
        turn = bridge.start_turn(
            "Reply exactly: OK", cwd=workspace,
            permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
        )
        try:
            for event in turn.events(timeout=90):
                if event.type not in observed:
                    observed.append(event.type)
                if event.type == "AgentMessageCompleted":
                    final_text = event.data.get("final_text", "")
                if event.type == "TokenUsageUpdated":
                    usage = event.data.get("tokenUsage")
        finally:
            turn.close()
    except Exception as exc:
        print(json.dumps({"version": bridge.get_version(), "auth_available": auth, "exit_code": 1, "content": final_text, "latency_ms": int((time.monotonic()-started)*1000), "error": str(exc)}))
        return 1
    required = {"TurnStarted", "AgentMessageDelta", "TurnCompleted"}
    ok = required.issubset(observed) and final_text.strip() == "OK"
    print(json.dumps({"version": bridge.get_version(), "auth_available": auth, "exit_code": 0 if ok else 1, "events": observed, "content": final_text, "usage": usage, "latency_ms": int((time.monotonic()-started)*1000), "error": None if ok else "Required event or exact response missing"}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
