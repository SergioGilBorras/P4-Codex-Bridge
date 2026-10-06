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
    cwd = ROOT / "tests_real" / "smoke_workspace"
    cwd.mkdir(parents=True, exist_ok=True)
    bridge = CodexBridge(allowed_roots=(cwd,))
    try:
        servers = bridge.list_configured_mcps(cwd=cwd, timeout_seconds=30)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": type(exc).__name__}))
        return 1
    print(json.dumps({
        "source": "diagnostic_app_server", "inference_turns": 0,
        "session_visible": "unknown", "servers": servers,
        "note": "May initialize configured local MCP servers. Advertised tool descriptors do not prove callable, child-visible to exec, or effective-for-run.",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
