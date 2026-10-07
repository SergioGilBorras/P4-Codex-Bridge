"""Manual diagnostic MCP inventory; no model inference or tool invocation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from p4_codex_bridge import CodexBridge


def main() -> int:
    cwd = ROOT / "tests_real" / "context_workspace"
    bridge = CodexBridge(allowed_roots=(cwd,))
    try:
        servers = bridge.list_configured_mcps(cwd=cwd, timeout_seconds=30)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": type(exc).__name__}))
        return 1
    known_auth = {"unknown", "unsupported", "authenticated", "required", "notrequired"}
    sanitized = []
    for item in servers:
        auth = str(item.get("auth_status", "unknown")).lower()
        sanitized.append({
            "name": item.get("name"), "configured": item.get("configured"),
            "enabled": item.get("enabled"), "auth_status": auth if auth in known_auth else "unknown",
            "runtime_status": item.get("runtime_status"),
            "tools_advertised": item.get("tools_advertised"), "tool_count": item.get("tool_count"),
            "callable": item.get("callable"), "child_visible": item.get("child_visible"),
            "child_context": item.get("child_context"), "effective_for_run": item.get("effective_for_run"),
            "startup_error": item.get("tools_error"),
        })
    print(json.dumps({
        "source": "diagnostic_app_server", "inference_turns": 0,
        "session_visible": "unknown", "servers": sanitized,
        "note": "Advertised descriptors do not prove callable or effective for a separate exec run. The diagnostic may start configured MCP servers, but invokes no tools.",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
