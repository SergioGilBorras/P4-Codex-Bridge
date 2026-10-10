from __future__ import annotations

import json
from tests_py._portable_temp import TemporaryDirectory
import unittest
from pathlib import Path
from unittest.mock import patch

from p4_codex_bridge.service import ForegroundService, ServiceConfig, _ensure_service_schema, _connect
from p4_codex_bridge.service_client import (CodexServiceClient, CreateThreadRequest,
    ExecRunSubmission, StartTurnRequest)
from p4_codex_bridge.security import ProjectTrust, RunSecurityPolicy
from p4_codex_bridge.errors import ConflictError, RunSecurityRejectedError, ServiceUnavailableError

FAKE_POLICY = RunSecurityPolicy(project_trust=ProjectTrust.TRUSTED, allow_external_mcps=True,
    allow_side_effect_mcps=True, explicit_risk_acknowledgement=True, policy_id="offline-fake")


class ServiceClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        self.db_path = self.state / "runs.sqlite3"
        _ensure_service_schema(self.db_path)
        self.client = CodexServiceClient(self.state)
        self.live = {"running": True, "instance_id": "svc_test", "codex_version": "FAKE"}

    def tearDown(self):
        self.temp.cleanup()

    def test_typed_payload_validation_and_size_bounds(self):
        with self.assertRaisesRegex(RunSecurityRejectedError, "effective_external_mcp_set_unknown"):
            ExecRunSubmission("safe default", str(self.workspace)).payload()
        with self.assertRaises(ValueError):
            ExecRunSubmission("x", "relative").payload()
        with self.assertRaises(ValueError):
            ExecRunSubmission("x" * (512 * 1024 + 1), str(self.workspace)).payload()
        with self.assertRaisesRegex(ValueError, "on-request"):
            CreateThreadRequest(str(self.workspace), sandbox="danger-full-access", approval_policy="never").payload()
        with self.assertRaises(TypeError):
            self.client.submit_exec_run({"prompt": "x"})
        request = ExecRunSubmission("hola", str(self.workspace), metadata={"agent_name": "Test"}, security_policy=FAKE_POLICY)
        self.assertEqual(request.payload()["metadata"]["agent_name"], "Test")
        self.assertIs(request.payload()["ephemeral"], True)
        persistent = ExecRunSubmission("continue later", str(self.workspace), security_policy=FAKE_POLICY,
                                       ephemeral=False)
        self.assertIs(persistent.payload()["ephemeral"], False)
        for invalid in (1, 0, "false", None):
            with self.subTest(ephemeral=invalid), self.assertRaisesRegex(ValueError, "ephemeral must be a boolean"):
                ExecRunSubmission("x", str(self.workspace), security_policy=FAKE_POLICY,
                                  ephemeral=invalid).payload()

    @patch("p4_codex_bridge.service_client.read_service_state")
    def test_service_absent_fails_without_starting_daemon(self, state):
        state.return_value = {"running": False, "state": "STOPPED"}
        with self.assertRaisesRegex(ServiceUnavailableError, "not running"):
            self.client.create_thread(CreateThreadRequest(str(self.workspace), security_policy=FAKE_POLICY))

    def test_version_and_help_import_cli_without_runtime_client(self):
        import subprocess
        import sys
        project = Path(__file__).resolve().parents[1]
        code = "import sys; import p4_codex_bridge.cli; assert 'p4_codex_bridge.client' not in sys.modules; from p4_codex_bridge.cli import main;\ntry: main(['--version'])\nexcept SystemExit as e: assert e.code == 0\nassert 'p4_codex_bridge.client' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", code], cwd=project, capture_output=True, text=True, timeout=5, shell=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        from p4_codex_bridge import __version__
        self.assertIn(__version__, result.stdout)

    @patch("p4_codex_bridge.service_client.read_service_state")
    def test_submit_is_typed_and_idempotent(self, state):
        state.return_value = self.live
        req = ExecRunSubmission("Reply exactly: OK", str(self.workspace), security_policy=FAKE_POLICY)
        first = self.client._submit("SUBMIT_EXEC_RUN", req.payload(), idempotency_key="stable-key")
        again = self.client._submit("SUBMIT_EXEC_RUN", req.payload(), idempotency_key="stable-key")
        self.assertEqual(first, again)
        with self.assertRaisesRegex(ConflictError, "different command"):
            self.client._submit("CREATE_THREAD", CreateThreadRequest(str(self.workspace), security_policy=FAKE_POLICY).payload(), idempotency_key="stable-key")
        with _connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM bridge_runtime_commands").fetchone()[0], 1)

    @patch("p4_codex_bridge.service_client.read_service_state")
    def test_wait_command_returns_ack_and_timeout(self, state):
        state.return_value = self.live
        command_id = self.client._submit("CREATE_THREAD", CreateThreadRequest(str(self.workspace), security_policy=FAKE_POLICY).payload())
        waiting = self.client.wait_command(command_id, timeout=0)
        self.assertEqual(waiting.status, "SUBMITTED")
        with _connect(self.db_path) as db:
            db.execute("UPDATE bridge_runtime_commands SET status='COMPLETED',result=? WHERE command_id=?",
                       (json.dumps({"thread_id": "th_fake"}), command_id))
        done = self.client.wait_command(command_id, timeout=0)
        self.assertEqual(done.result, {"thread_id": "th_fake"})

    def test_service_claim_is_atomic_and_crash_recovery_does_not_replay(self):
        cfg = ServiceConfig(state_dir=self.state, cwd=self.workspace, log_dir=self.root / "logs", allowed_roots=(self.workspace,))
        service = ForegroundService(cfg, fake_command=["fake"])
        with _connect(self.db_path) as db:
            db.execute("INSERT INTO bridge_runtime_commands(command_id,command_type,submitted_at,submitted_by,payload,idempotency_key,status) VALUES('cmd1','CREATE_THREAD','2026-01-01','pid','{}','key','SUBMITTED')")
        first = service._claim_runtime_command()
        self.assertEqual(first["command_id"], "cmd1")
        self.assertEqual(first["payload"], "{}")
        with _connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT payload FROM bridge_runtime_commands WHERE command_id='cmd1'").fetchone()[0], "")
        self.assertIsNone(service._claim_runtime_command())
        service._recover_runtime_commands()
        with _connect(self.db_path) as db:
            row = db.execute("SELECT status,error FROM bridge_runtime_commands WHERE command_id='cmd1'").fetchone()
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("outcome is unknown", row["error"])
        self.assertIsNone(service._claim_runtime_command())

    def test_service_worker_routes_create_and_start_turn_to_runtime_manager(self):
        cfg = ServiceConfig(state_dir=self.state, cwd=self.workspace, log_dir=self.root / "logs", allowed_roots=(self.workspace,))
        service = ForegroundService(cfg)
        calls = []
        workspace = self.workspace

        class Manager:
            def create_thread(self, **kwargs):
                calls.append(("create", kwargs))
                return type("Thread", (), {"thread_id": "th_1", "cwd": str(workspace)})()
            def start_turn(self, thread_id, prompt, **kwargs):
                calls.append(("turn", thread_id, prompt, kwargs))
                return type("Turn", (), {"bridge_run_id": "br_1", "thread_id": thread_id, "turn_id": "tr_1", "status": type("Status", (), {"value": "QUEUED"})()})()

        service.manager = Manager()
        service.instance_id = "svc_test"
        for command_id, kind, payload in (
            ("create", "CREATE_THREAD", CreateThreadRequest(str(self.workspace), security_policy=FAKE_POLICY).payload()),
            ("turn", "START_TURN", StartTurnRequest("th_1", "next").payload()),
        ):
            with _connect(self.db_path) as db:
                db.execute("INSERT INTO bridge_runtime_commands(command_id,command_type,submitted_at,submitted_by,payload,idempotency_key,status,claimed_by) VALUES(?,?,?,?,?,?,?,?)",
                    (command_id, kind, "2026-01-01", "pid", json.dumps(payload), command_id, "CLAIMED", "svc_test"))
            service._process_runtime_command({"command_id": command_id, "command_type": kind, "payload": json.dumps(payload)})
            result = self.client.wait_command(command_id, timeout=0)
            self.assertEqual(result.status, "COMPLETED", result.error)
        self.assertEqual(calls[0][0], "create")
        self.assertEqual(calls[1][0], "turn")
        self.assertEqual(calls[1][1], "th_1")

    def test_service_worker_routes_exec_to_existing_managed_bridge_api(self):
        cfg = ServiceConfig(state_dir=self.state, cwd=self.workspace, log_dir=self.root / "logs", allowed_roots=(self.workspace,))
        service = ForegroundService(cfg)
        received = []
        service.exec_bridge = type("Bridge", (), {"start": lambda _self, prompt, **kwargs:
            (received.append((prompt, kwargs)) or type("Run", (), {"bridge_run_id": "br_exec", "status": type("Status", (), {"value": "QUEUED"})()})())})()
        payload = ExecRunSubmission("safe fake", str(self.workspace), metadata={"agent_name": "Fixture"},
                                    output_schema={"type": "object"}, security_policy=FAKE_POLICY,
                                    ephemeral=False).payload()
        with _connect(self.db_path) as db:
            db.execute("INSERT INTO bridge_runtime_commands(command_id,command_type,submitted_at,submitted_by,payload,idempotency_key,status,claimed_by) VALUES('exec','SUBMIT_EXEC_RUN','2026-01-01','pid',?,'exec','CLAIMED','svc_test')", (json.dumps(payload),))
        service.instance_id = "svc_test"
        service._process_runtime_command({"command_id": "exec", "command_type": "SUBMIT_EXEC_RUN", "payload": json.dumps(payload)})
        result = self.client.wait_command("exec", timeout=0)
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.result["bridge_run_id"], "br_exec")
        self.assertEqual(received[0][0], "safe fake")
        self.assertEqual(received[0][1]["metadata"]["agent_name"], "Fixture")
        self.assertEqual(received[0][1]["output_schema"], {"type": "object"})
        self.assertIs(received[0][1]["ephemeral"], False)

    def test_service_receiver_revalidates_ephemeral_and_keeps_old_payload_default(self):
        cfg = ServiceConfig(state_dir=self.state, cwd=self.workspace, log_dir=self.root / "logs", allowed_roots=(self.workspace,))
        service = ForegroundService(cfg)
        received = []
        service.exec_bridge = type("Bridge", (), {"start": lambda _self, prompt, **kwargs:
            (received.append(kwargs) or type("Run", (), {"bridge_run_id": "br_exec", "status": type("Status", (), {"value": "QUEUED"})()})())})()
        service.instance_id = "svc_test"
        base = ExecRunSubmission("safe fake", str(self.workspace), security_policy=FAKE_POLICY).payload()
        old_client_payload = {key: value for key, value in base.items() if key != "ephemeral"}
        invalid_payload = {**old_client_payload, "ephemeral": "false"}
        for command_id, payload in (("old", old_client_payload), ("invalid", invalid_payload)):
            with _connect(self.db_path) as db:
                db.execute("INSERT INTO bridge_runtime_commands(command_id,command_type,submitted_at,submitted_by,payload,idempotency_key,status,claimed_by) VALUES(?,?,?,?,?,?,?,?)",
                    (command_id, "SUBMIT_EXEC_RUN", "2026-01-01", "pid", json.dumps(payload), command_id, "CLAIMED", "svc_test"))
            service._process_runtime_command({"command_id": command_id, "command_type": "SUBMIT_EXEC_RUN", "payload": json.dumps(payload)})
        old_result = self.client.wait_command("old", timeout=0)
        invalid_result = self.client.wait_command("invalid", timeout=0)
        self.assertEqual(old_result.status, "COMPLETED", old_result.error)
        self.assertIs(received[0]["ephemeral"], True)
        self.assertEqual(invalid_result.status, "FAILED")
        self.assertIn("ephemeral must be a boolean", invalid_result.error)
        self.assertEqual(len(received), 1)

    def test_daemon_revalidates_external_security_policy_before_runtime_call(self):
        cfg = ServiceConfig(state_dir=self.state, cwd=self.workspace, log_dir=self.root / "logs", allowed_roots=(self.workspace,))
        service = ForegroundService(cfg)

        class Manager:
            def create_thread(self, **kwargs):
                raise AssertionError("security rejection must happen before runtime dispatch")

        service.manager = Manager()
        service.instance_id = "svc_test"
        policy = RunSecurityPolicy(require_mcp_isolation=True, policy_id="untrusted-client")
        payload = {"cwd": str(self.workspace), "profile": "analysis", "model": None,
                   "sandbox": "read-only", "approval_policy": "never",
                   "config_policy": "isolated", "metadata": {},
                   "security_policy": policy.to_dict()}
        with _connect(self.db_path) as db:
            db.execute("INSERT INTO bridge_runtime_commands(command_id,command_type,submitted_at,submitted_by,payload,idempotency_key,status,claimed_by) VALUES('unsafe','CREATE_THREAD','2026-01-01','pid',?,'unsafe','CLAIMED','svc_test')",
                       (json.dumps(payload),))
        service._process_runtime_command({"command_id": "unsafe", "command_type": "CREATE_THREAD",
                                          "payload": json.dumps(payload)})
        result = self.client.wait_command("unsafe", timeout=0)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("MCP per-run isolation", result.error)


if __name__ == "__main__":
    unittest.main()


class CrossProcessFakeDaemonTests(unittest.TestCase):
    def test_cli_submit_create_turn_ps_watch_and_shutdown_across_processes(self):
        import os
        import subprocess
        import sys
        import time
        from p4_codex_bridge.service import service_status
        with TemporaryDirectory(prefix="p4-cross-process-") as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            state = root / "state"
            config = root / "service.toml"
            config.write_text(f'[service]\ncwd = "{workspace.as_posix()}"\n', encoding="utf-8")
            project = Path(__file__).resolve().parents[1]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(project) + os.pathsep + env.get("PYTHONPATH", "")
            service = subprocess.Popen([sys.executable, "-m", "p4_codex_bridge", "service", "run", "--fake",
                "--config", str(config), "--state-dir", str(state)], cwd=project, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)

            def cli(*args, input_data=None, timeout=10):
                return subprocess.run([sys.executable, "-m", "p4_codex_bridge", *args], cwd=project,
                    env=env, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, timeout=timeout, shell=False)

            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if service.poll() is not None:
                        self.fail("fake daemon exited before reporting healthy")
                    if service_status(state).get("state") == "HEALTHY":
                        break
                    time.sleep(.2)
                else:
                    self.fail("fake daemon did not become healthy")
                create = cli("thread", "create", "--config", str(config), "--state-dir", str(state), "--json",
                    input_data=json.dumps({"cwd": str(workspace), "metadata": {"agent_name": "CrossProcessDemo", "task_key": "DEMO-1"}, "security_policy": FAKE_POLICY.to_dict()}))
                self.assertEqual(create.returncode, 0, create.stderr)
                thread_result = json.loads(create.stdout)
                self.assertEqual(thread_result["status"], "COMPLETED")
                thread_id = thread_result["result"]["thread_id"]
                turn = cli("turn", "start", "--config", str(config), "--state-dir", str(state), "--json",
                    input_data=json.dumps({"thread_id": thread_id, "prompt": "Reply exactly: FAKE_OK"}))
                self.assertEqual(turn.returncode, 0, turn.stderr)
                turn_result = json.loads(turn.stdout)
                run_id = turn_result["result"]["bridge_run_id"]
                deadline = time.monotonic() + 15
                row = None
                while time.monotonic() < deadline:
                    listing = cli("ps", "--json", "--state-dir", str(state))
                    self.assertEqual(listing.returncode, 0, listing.stderr)
                    row = next((item for item in json.loads(listing.stdout) if item["bridge_run_id"] == run_id), None)
                    if row and row["status"] == "COMPLETED":
                        break
                    time.sleep(.25)
                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "COMPLETED")
                watched = cli("watch", run_id, "--state-dir", str(state))
                self.assertEqual(watched.returncode, 0, watched.stderr)
                self.assertIn("TurnCompleted", watched.stdout)
                stop = cli("service", "stop", "--config", str(config), "--state-dir", str(state), "--timeout", "30",
                           timeout=40)
                self.assertEqual(stop.returncode, 0, stop.stderr)
                service.wait(timeout=40)
            finally:
                if service.poll() is None:
                    try:
                        from p4_codex_bridge.service import request_service_action
                        request_service_action(state, "stop", timeout=10)
                        service.wait(timeout=15)
                    except Exception:
                        # Do not terminate an unverified process tree during cleanup.
                        pass
