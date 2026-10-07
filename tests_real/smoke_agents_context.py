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

LUNA_MODEL_ID = "gpt-6-luna"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", choices=("isolated", "project", "explicit"), required=True)
    parser.add_argument(
        "--allow-unfiltered-mcps", action="store_true",
        help="Acknowledge that this Codex CLI version has no verified per-run MCP allowlist.",
    )
    args = parser.parse_args()
    cwd = ROOT / "tests_real" / "context_workspace"
    auth = "Logged in using ChatGPT" in probe(["login", "status"], timeout=15)
    if not auth:
        print(json.dumps({"status": "SKIPPED_AUTH_UNAVAILABLE", "auth_available": False}))
        return 2
    bridge = CodexBridge(allowed_roots=(cwd,))
    try:
        models = bridge.list_models(timeout_seconds=45)
    except Exception as exc:
        print(json.dumps({"status": "SKIPPED_MODEL_DISCOVERY_ERROR", "requested_model": LUNA_MODEL_ID,
                          "error_class": type(exc).__name__, "inference_turns": 0}))
        return 3
    if not any(item.get("id") == LUNA_MODEL_ID or item.get("model") == LUNA_MODEL_ID for item in models):
        print(json.dumps({"status": "SKIPPED_MODEL_UNAVAILABLE", "requested_model": LUNA_MODEL_ID,
                          "model_available_in_catalog": False, "inference_turns": 0}))
        return 3
    if not args.allow_unfiltered_mcps:
        print(json.dumps({"status": "SKIPPED_UNFILTERED_MCP_POLICY", "requested_model": LUNA_MODEL_ID,
                          "model_available_in_catalog": True, "inference_turns": 0,
                          "note": "No model run started; re-run only after explicitly acknowledging unfiltered MCP inheritance."}))
        return 4
    started = time.monotonic()
    options = {"config_policy": args.policy}
    if args.policy == "explicit":
        options["reasoning_effort"] = "low"
    result = bridge.run(
        "What is the marker? Do not use tools or access external services. Reply with only the exact marker.", cwd=cwd,
        profile="analysis", permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
        timeout_seconds=90, model=LUNA_MODEL_ID, **options,
    )
    matched = result.content.strip() == "P4_AGENTS_OK"
    print(json.dumps({
        "status": "PASS" if result.ok and matched else "FAIL",
        "version": bridge.get_version(), "auth_available": auth,
        "config_policy": args.policy, "cwd": str(cwd), "exit_code": result.exit_code,
        "marker_matched": matched, "session_visible": "unknown",
        "child_visible": "confirmed" if matched else "not_confirmed",
        "effective_for_run": "confirmed" if matched else "not_confirmed",
        "requested_model": LUNA_MODEL_ID, "effective_model": None, "model_verified": False,
        "model_verification": "Codex exec result does not expose a verified effective model field",
        "usage": None, "usage_note": "No verified token usage breakdown is exposed by this exec result",
        "latency_ms": int((time.monotonic() - started) * 1000),
        "error": result.error,
    }, ensure_ascii=False))
    return 0 if result.ok and matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
