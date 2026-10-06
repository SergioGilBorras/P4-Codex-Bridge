"""Manual single-turn AGENTS.md marker check for one selected config policy."""
from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", choices=("isolated", "project", "explicit"), required=True)
    args = parser.parse_args()
    cwd = ROOT / "tests_real" / "context_workspace"
    auth = "Logged in using ChatGPT" in probe(["login", "status"], timeout=15)
    if not auth:
        print(json.dumps({"auth_available": False, "error": "Codex ChatGPT login is unavailable"}))
        return 2
    bridge = CodexBridge(allowed_roots=(cwd,))
    started = time.monotonic()
    options = {"config_policy": args.policy}
    if args.policy == "explicit":
        options["reasoning_effort"] = "low"
    result = bridge.run(
        "What is the marker? Do not use tools or access external services. Reply with only the exact marker.", cwd=cwd,
        profile="analysis", permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
        timeout_seconds=90, **options,
    )
    matched = result.content.strip() == "P4_AGENTS_OK"
    print(json.dumps({
        "version": bridge.get_version(), "auth_available": auth,
        "config_policy": args.policy, "cwd": str(cwd), "exit_code": result.exit_code,
        "content": result.content, "session_visible": "unknown",
        "child_visible": "confirmed" if matched else "not_confirmed",
        "effective_for_run": "confirmed" if matched else "not_confirmed",
        "usage": None, "latency_ms": int((time.monotonic() - started) * 1000),
        "error": result.error,
    }, ensure_ascii=False))
    return 0 if result.ok and matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
