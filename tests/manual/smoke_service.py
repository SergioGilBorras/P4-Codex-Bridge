"""Manual one-turn foreground-service smoke. Never part of automated tests.

Requires an explicit --run-real-turn acknowledgement. It uses Luna only when
the installed model catalog lists the exact id; it never falls back.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from dataclasses import asdict

from portable_tempdirs import temporary_directory

try:
    from p4_codex_bridge import CodexBridge, ProjectTrust, RunSecurityPolicy
    from p4_codex_bridge.service import ForegroundService, ServiceConfig
except ModuleNotFoundError:
    # Allow direct source-checkout invocation while preferring an installed
    # package when the script runs from a clean release venv.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from p4_codex_bridge import CodexBridge, ProjectTrust, RunSecurityPolicy
    from p4_codex_bridge.service import ForegroundService, ServiceConfig
from p4_codex_bridge.service import request_service_action, service_metrics, service_status


MODEL_ID = "gpt-6-luna"


def _write_service_config(root: Path, workspace: Path) -> Path:
    config_path = root / "service.toml"
    config_path.write_text("[service]\n" +
        "state_dir = " + json.dumps(str(root / "state")) + "\n" +
        "cwd = " + json.dumps(str(workspace)) + "\n" +
        "[logging]\n" +
        "log_dir = " + json.dumps(str(root / "logs")) + "\n", encoding="utf-8")
    return config_path


def _service_client_call(operation: str, request: dict, state_dir: Path, cwd: Path) -> dict:
    """Submit through a separate process, exercising the installed public client."""
    code = """
import dataclasses, json, sys
from p4_codex_bridge import CodexServiceClient, CreateThreadRequest, StartTurnRequest, RunSecurityPolicy
value = json.load(sys.stdin)
client = CodexServiceClient(state_dir=value['state_dir'])
request = value['request']
security = RunSecurityPolicy.from_dict(request.pop('security_policy'))
if value['operation'] == 'CREATE_THREAD':
    result = client.create_thread(CreateThreadRequest(**request, security_policy=security), timeout=60)
else:
    result = client.start_turn(StartTurnRequest(**request, security_policy=security), timeout=60)
print(json.dumps(dataclasses.asdict(result), ensure_ascii=False))
"""
    child = subprocess.run([sys.executable, "-c", code], cwd=cwd,
        input=json.dumps({"operation": operation, "state_dir": str(state_dir), "request": request}),
        capture_output=True, text=True, encoding="utf-8", timeout=75, shell=False,
        env={**os.environ, "P4_CODEX_BRIDGE_STATE_DIR": str(state_dir)})
    if child.returncode != 0:
        raise RuntimeError("cross-process service client failed: " + child.stderr[-500:])
    result = json.loads(child.stdout)
    if result.get("status") != "COMPLETED" or not result.get("result"):
        raise RuntimeError("cross-process service command did not complete")
    return result["result"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-real-turn", action="store_true", help="explicitly allow one real Codex turn")
    parser.add_argument("--allow-unfiltered-mcps", action="store_true",
        help="acknowledge that the app-server run cannot filter configured MCP tools")
    args = parser.parse_args()
    if not args.run_real_turn or not args.allow_unfiltered_mcps:
        parser.error("pass --run-real-turn and --allow-unfiltered-mcps to acknowledge one turn and the configured MCP surface")

    catalog = CodexBridge().list_models()
    if not any(model.get("id") == MODEL_ID for model in catalog):
        print(json.dumps({"status": "SKIPPED_MODEL_UNAVAILABLE", "requested_model": MODEL_ID}))
        return 2

    with temporary_directory("P4CodexServiceSmoke") as temp:
        root = Path(temp).resolve()
        workspace = root / "workspace"
        workspace.mkdir()
        config_path = _write_service_config(root, workspace)
        config = ServiceConfig.load(config_path)
        security = RunSecurityPolicy(project_trust=ProjectTrust.TRUSTED,
            allow_external_mcps=True, allow_side_effect_mcps=True,
            explicit_risk_acknowledgement=True,
            policy_id="manual-luna-smoke-unfiltered-mcp-ack")
        service = ForegroundService(config)
        service_thread = threading.Thread(target=service.run, name="p4-codex-service-smoke", daemon=False)
        started = time.monotonic()
        service_thread.start()
        try:
            deadline = time.monotonic() + config.startup_timeout_seconds + 15
            while time.monotonic() < deadline:
                snapshot = service_status(config.state_dir)
                if snapshot.get("state") == "HEALTHY" and service.manager is not None:
                    break
                if not service_thread.is_alive():
                    raise RuntimeError("foreground service exited during startup")
                time.sleep(0.1)
            else:
                raise TimeoutError("foreground service did not become healthy")

            thread_command = _service_client_call("CREATE_THREAD", {
                "cwd": str(workspace), "profile": "analysis", "model": MODEL_ID,
                "sandbox": "read-only", "approval_policy": "never",
                "config_policy": "isolated",
                "metadata": {"agent_name": "ServiceSmoke", "agent_role": "validation"},
                "security_policy": security.to_dict()}, config.state_dir, root)
            thread_id = thread_command["thread_id"]
            turn_command = _service_client_call("START_TURN", {
                "thread_id": thread_id, "prompt": "Reply exactly: OK",
                "timeout_seconds": 150, "metadata": {"agent_name": "ServiceSmoke"},
                "access_mode": "READ", "resource_priority": 0,
                "security_policy": security.to_dict()}, config.state_dir, root)
            run_id = turn_command["bridge_run_id"]
            turn_id = turn_command["turn_id"]
            watch = subprocess.Popen([sys.executable, "-m", "p4_codex_bridge", "watch", run_id,
                "--follow", "--json", "--state-dir", str(config.state_dir)],
                cwd=root, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                shell=False, env={**os.environ, "P4_CODEX_BRIDGE_STATE_DIR": str(config.state_dir)})
            try:
                watch_stdout, watch_stderr = watch.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                watch.kill()
                watch.communicate()
                raise TimeoutError("service watch timed out")
            if watch.returncode != 0:
                raise RuntimeError("read-only watch failed: " + watch_stderr[-500:])
            final_turn = service.manager.turns.get(turn_id)
            if final_turn is None or final_turn.status.value != "COMPLETED" or final_turn.final_text.strip() != "OK":
                raise RuntimeError("service smoke turn did not complete with exact OK")
            resources = service.manager.get_resource_status()
            approvals = service.manager.list_pending_approvals()
            if resources.get("queue_length") != 0 or resources.get("workspace_locks") or approvals:
                raise RuntimeError("service smoke left queued work, workspace locks, or pending approvals")
            events = [json.loads(line) for line in watch_stdout.splitlines() if line.strip()]
            print(json.dumps({"status": "PASS", "bridge_run_id": run_id,
                "thread_id": thread_id, "turn_id": turn_id,
                "requested_model": MODEL_ID, "effective_model": None,
                "model_verified": "NOT_CONFIRMED; app-server event does not expose effective model in this API",
                "final_text": final_turn.final_text,
                "lifecycle_events": [event.get("type") for event in events],
                "latency_seconds": round(time.monotonic() - started, 3),
                "token_usage": service.manager.get_metrics().get("token_usage"),
                "security_acknowledgement": "explicit unfiltered MCP risk acknowledgement",
                "resources_released": True}, ensure_ascii=False))
            return 0
        finally:
            try:
                request_service_action(config.state_dir, "stop", timeout=config.shutdown_timeout_seconds + 10)
            except Exception:
                service.stop_event.set()
            service_thread.join(timeout=config.shutdown_timeout_seconds + 10)
            if service_thread.is_alive():
                raise RuntimeError("service thread did not stop cleanly")
            final_status = service_status(config.state_dir)
            final_metrics = service_metrics(config.state_dir)
            cleanup = {"service_stopped": final_status.get("state") == "STOPPED",
                "active_runs": final_metrics.get("active_runs"),
                "queue_length": final_status.get("queue_length"),
                "workspace_locks": final_status.get("workspace_locks"),
                "pending_approvals": final_status.get("waiting_approvals"),
                "pending_payloads": final_metrics.get("queued_runs")}
            print(json.dumps({"post_run": final_status, "metrics": final_metrics,
                "cleanup": cleanup}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
