"""Manual read-only smoke test for the Python API; excluded from unittest discovery."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from p4_codex_bridge import CodexBridge
from p4_codex_bridge.runtime import probe, redact


def main() -> int:
    workspace = Path(__file__).resolve().parents[1] / "tests" / "smoke_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    auth = probe(["login", "status"], timeout=15).strip()
    authenticated = "logged in using chatgpt" in auth.lower()
    result_data = {
        "version": "",
        "auth_available": authenticated,
        "exit_code": None,
        "content": "",
        "latency_ms": None,
        "error": None,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="p4-codex-smoke-", dir=workspace) as state_dir:
            bridge = CodexBridge(state_dir=state_dir, allowed_roots=(workspace,))
            result_data["version"] = bridge.get_version()
            if not authenticated:
                result_data["error"] = "Codex ChatGPT login is unavailable; live call skipped"
                print(json.dumps(result_data, ensure_ascii=False))
                return 2
            result = bridge.run(
                "Reply exactly with:\nP4_CODEX_BRIDGE_OK",
                cwd=workspace,
                profile="analysis",
                timeout_seconds=120,
            )
            result_data.update(
                exit_code=result.exit_code,
                content=result.content,
                latency_ms=result.duration_ms,
                error=result.error,
            )
            print(json.dumps(result_data, ensure_ascii=False))
            return 0 if result.ok and result.content.strip() == "P4_CODEX_BRIDGE_OK" else 1
    except Exception as exc:
        result_data["error"] = {"code": "SMOKE_ERROR", "message": redact(str(exc))}
        print(json.dumps(result_data, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
