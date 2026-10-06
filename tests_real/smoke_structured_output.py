"""Manual one-turn check for CLI structured output; never part of unittest."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from p4_codex_bridge import CodexBridge, CodexPermissions, SandboxMode, ApprovalPolicy
from p4_codex_bridge.runtime import probe


def main() -> int:
    cwd = ROOT / "tests_real" / "smoke_workspace"
    cwd.mkdir(parents=True, exist_ok=True)
    auth = "Logged in using ChatGPT" in probe(["login", "status"], timeout=15)
    if not auth:
        print(json.dumps({"auth_available": False, "error": "Codex ChatGPT login is unavailable"}))
        return 2
    bridge = CodexBridge(allowed_roots=(cwd,))
    started = time.monotonic()
    result = bridge.run(
        "Return JSON with ok=true. Do not use tools or access external services.",
        cwd=cwd,
        profile="analysis",
        permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
        output_schema={
            "type": "object", "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"], "additionalProperties": False,
        },
        timeout_seconds=90,
    )
    output = {
        "version": bridge.get_version(), "auth_available": auth,
        "exit_code": result.exit_code, "content": result.text_output,
        "structured_output": result.structured_output,
        "usage": None, "usage_note": "codex exec result currently exposes no verified token usage field",
        "latency_ms": int((time.monotonic() - started) * 1000), "error": result.error,
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0 if result.ok and result.structured_output == {"ok": True} else 1


if __name__ == "__main__":
    raise SystemExit(main())
