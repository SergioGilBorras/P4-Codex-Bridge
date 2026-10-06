from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

from p4_codex_bridge import (
    ApprovalPolicy,
    CodexBridge,
    CodexPermissions,
    RunStatus,
    SandboxMode,
)
from p4_codex_bridge.scheduler import ResourceScheduler, RuntimeLimits


FAKE_CODEX = r'''import json, os, sys, time
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli fake-1.0")
elif args == ["--help"]:
    print("Usage: codex\nexec app-server login mcp resume agents features --ask-for-approval never on-request")
elif args == ["exec", "--help"]:
    print("Usage: codex exec --json --output-schema --output-last-message --model --sandbox read-only workspace-write danger-full-access --ask-for-approval never on-request -C --ignore-user-config stdin")
elif args[:2] == ["exec", "resume"] and "--help" in args:
    print("Usage: codex exec resume SESSION_ID [PROMPT] --json --output-schema --output-last-message --model -c --ignore-user-config")
elif args[:2] == ["exec", "fork"] and "--help" in args:
    print("Usage: codex exec fork SESSION_ID [PROMPT] --json --output-schema --output-last-message --model -c --ignore-user-config")
elif args[:2] == ["exec", "review"] and "--help" in args:
    print("Usage: codex exec review --uncommitted --base BASE --commit COMMIT --title TITLE --json")
elif args == ["app-server", "--help"]:
    print("Usage: codex app-server [experimental] --listen stdio:// unix:// ws://")
elif args[:2] == ["app-server", "--listen"]:
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("id") == 1:
            print(json.dumps({"jsonrpc":"2.0", "id":1, "result":{"codexHome":"/tmp/codex"}}), flush=True)
        elif request.get("method") == "model/list":
            cursor = request["params"].get("cursor")
            data = [{"model":"fake-model", "id":"fake-model", "isDefault":True}] if not cursor else []
            print(json.dumps({"jsonrpc":"2.0", "id":request["id"], "result":{"data":data,"nextCursor":None}}), flush=True)
        elif request.get("method") == "config/read":
            result = {"config":{"model":"fake-model", "api_key":"must-not-leak"}, "origins":{"model":{"name":{"type":"project"}}}, "layers":[{"name":{"type":"user"}},{"name":{"type":"project"}}]}
            print(json.dumps({"jsonrpc":"2.0", "id":request["id"], "result":result}), flush=True)
        elif request.get("method") == "mcpServerStatus/list":
            result = {"data":[{"name":"fixture-mcp","runtimeStatus":"connected","authStatus":"unknown","tools":{"search":{}}}]}
            print(json.dumps({"jsonrpc":"2.0", "id":request["id"], "result":result}), flush=True)
        elif request.get("method") == "skills/list":
            result = {"data":[{"cwd":request["params"]["cwds"][0],"skills":[{"name":"fixture-skill","description":"fixture","enabled":True,"scope":"user"}]}]}
            print(json.dumps({"jsonrpc":"2.0", "id":request["id"], "result":result}), flush=True)
elif "exec" in args:
    model = args[args.index("--model") + 1] if "--model" in args else ""
    prompt = sys.stdin.read()
    if model == "timeout":
        time.sleep(20)
    if model == "slow":
        time.sleep(0.6)
    if model == "nonzero":
        print("ACCESS_TOKEN=abc123", file=sys.stderr)
        sys.exit(7)
    if model == "auth":
        print("Not logged in. Run codex login.", file=sys.stderr)
        sys.exit(1)
    if model == "empty":
        sys.exit(0)
    if model == "secret":
        content = json.dumps({"access_token":"do-not-leak", "answer":"Bearer abc.def"})
    elif model == "schema":
        schema_path = args[args.index("--output-schema") + 1]
        if not os.path.isfile(schema_path):
            sys.exit(8)
        content = json.dumps({"answer":"ok"})
    elif model == "schema-reject":
        schema = json.load(open(args[args.index("--output-schema") + 1], encoding="utf-8"))
        if not isinstance(schema.get("type"), str):
            print("invalid JSON Schema", file=sys.stderr)
            sys.exit(4)
        content = json.dumps({"ok":True})
    elif model == "bad-json":
        content = "not-json"
    elif model == "last-malformed":
        content = "malformed last output"
    elif model == "last-missing":
        content = "final text"
    elif model == "args":
        content = json.dumps(args)
    elif model == "unicode":
        content = "respuesta café 🧪"
    else:
        content = "got:" + prompt
    if model != "last-missing":
        path = args[args.index("--output-last-message") + 1] if "--output-last-message" in args else None
        if path:
            with open(path, "w", encoding="utf-8") as output:
                output.write("broken" if model == "last-malformed" else content)
    print(json.dumps({"type":"thread.started", "thread_id":"fake-session-123"}), flush=True)
    print(json.dumps({"type":"item.completed", "item":{"type":"agent_message", "text":content}}), flush=True)
else:
    sys.exit(2)
'''


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="p4-codex-test-")
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.codex = self.root / "fake_codex.py"
        self.codex.write_text(FAKE_CODEX, encoding="utf-8")
        self.cwd = self.root / "workspace"
        self.cwd.mkdir()
        self.override = patch.dict(os.environ, {"CODEX_BIN": str(self.codex)})
        self.override.start()
        self.bridge = CodexBridge(state_dir=self.state, allowed_roots=(self.root,), default_timeout_seconds=30)

    def tearDown(self) -> None:
        # The direct compatibility API collects/joins its own results. Only
        # scheduler-owned workers need an explicit join in this fixture.
        for run in self.bridge.list_runs():
            if run.backend != "exec":
                continue
            self.bridge._wait_worker_exit(run.bridge_run_id, timeout=10)
        self.override.stop()
        self.temp.cleanup()

    def run_model(self, model: str, **kwargs):
        # Ordinary fake executions test contracts, not Windows process startup
        # latency. Timeout behavior has dedicated cases with explicit short values.
        return self.bridge.run("hello", cwd=self.cwd, model=model, timeout_seconds=kwargs.pop("timeout_seconds", 30), **kwargs)

    def test_run_valid_and_prompt_is_passed_on_stdin(self):
        result = self.bridge.run("hello; $env:SECRET", cwd=self.cwd)
        self.assertTrue(result.ok)
        self.assertIn("hello; $env:SECRET", result.content)

    def test_managed_exec_start_uses_persistent_queue_and_dispatches_next(self):
        scheduler = ResourceScheduler(self.bridge.registry.path)
        limits = RuntimeLimits(global_max_active=1, app_server_max_active=1, exec_max_active=1,
                               max_active_threads=4, profile_limits={"analysis": 2})
        scheduler.persist_limits(limits)
        scheduler.limits = limits
        first = self.bridge.start("first", cwd=self.cwd, model="slow", access_mode="WRITE")
        second = self.bridge.start("second", cwd=self.cwd, access_mode="READ")
        self.assertEqual(first.backend, "exec")
        self.assertEqual(scheduler.get(first.bridge_run_id)["status"], "RUNNING")
        waiting = scheduler.get(second.bridge_run_id)
        self.assertEqual(waiting["status"], "WAITING_FOR_SLOT")
        self.assertEqual(waiting["waiting_reason"], "GLOBAL_LIMIT")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and scheduler.get(second.bridge_run_id)["status"] not in scheduler.TERMINAL:
            time.sleep(0.05)
        self.assertEqual(scheduler.get(first.bridge_run_id)["status"], "COMPLETED")
        self.assertEqual(scheduler.get(second.bridge_run_id)["status"], "COMPLETED")
        self.assertFalse((self.state / "scheduler_payloads").exists())

    def test_managed_exec_active_cancel_releases_shared_resources(self):
        scheduler = ResourceScheduler(self.bridge.registry.path)
        limits = RuntimeLimits(global_max_active=1, app_server_max_active=1, exec_max_active=1,
                               max_active_threads=4, profile_limits={"analysis": 2})
        scheduler.persist_limits(limits)
        scheduler.limits = limits
        run = self.bridge.start("slow", cwd=self.cwd, model="timeout", access_mode="WRITE")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            row = scheduler.get(run.bridge_run_id)
            if row and row.get("process_pid"):
                break
            time.sleep(0.05)
        cancelled = self.bridge.cancel(run.bridge_run_id, grace_seconds=2)
        self.assertEqual(cancelled.status, RunStatus.CANCELLED)
        self.assertEqual(scheduler.get(run.bridge_run_id)["status"], RunStatus.CANCELLED.value)
        self.assertEqual(scheduler.resources(limits)["workspace_locks"], [])

    def test_exec_recovery_uses_only_verified_result_and_never_replays_lost_work(self):
        scheduler = ResourceScheduler(self.bridge.registry.path)
        now = "2026-01-01T00:00:00+00:00"
        for run_id in ("br_recover_result", "br_recover_lost"):
            scheduler.submit(turn_id=run_id, thread_id=run_id, backend="exec", profile="analysis",
                workspace=self.cwd, prompt="synthetic", bridge_run_id=run_id, submitted_at=now)
            scheduler.dispatch(backend="exec")
            result_path = self.state / "results" / f"{run_id}.json"
            self.bridge.registry.create(run_id, backend="exec", cwd=str(self.cwd), model=None, profile="analysis",
                result_path=str(result_path))
            self.bridge.registry.update(run_id, status="RUNNING")
            scheduler.set_process(run_id, worker_pid=2_000_000_000, worker_identity="not-a-live-identity")
        result_path = self.state / "results" / "br_recover_result.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps({"ok": True, "bridge_run_id": "br_recover_result", "exit_code": 0,
            "content": "done", "stderr": "", "structured_output": None, "error": None, "duration_ms": 1}), encoding="utf-8")
        restarted = CodexBridge(state_dir=self.state, allowed_roots=(self.root,))
        self.assertEqual(scheduler.get("br_recover_result")["status"], "COMPLETED")
        self.assertEqual(scheduler.get("br_recover_lost")["status"], "LOST")
        self.assertEqual(restarted.recover_exec_runs(), {"active": [], "completed_from_result": [], "lost": []})

    def test_exec_and_app_server_share_workspace_lock_namespace(self):
        scheduler = ResourceScheduler(self.bridge.registry.path)
        limits = RuntimeLimits(global_max_active=2, app_server_max_active=1, exec_max_active=1,
                               max_active_threads=4, profile_limits={"analysis": 2})
        scheduler.persist_limits(limits)
        scheduler.limits = limits
        app = scheduler.submit(turn_id="turn-fake", thread_id="thread-fake", backend="app-server",
            profile="analysis", workspace=self.cwd, prompt="fake", access_mode="WRITE",
            bridge_run_id="br_fake_app", submitted_at="2026-01-01T00:00:00+00:00")
        self.assertEqual(scheduler.dispatch(backend="app-server")[0]["bridge_run_id"], app["bridge_run_id"])
        exec_run = self.bridge.start("exec waits", cwd=self.cwd, access_mode="WRITE")
        waiting = scheduler.get(exec_run.bridge_run_id)
        self.assertEqual(waiting["status"], "WAITING_FOR_SLOT")
        self.assertEqual(waiting["waiting_reason"], "WORKSPACE_LOCK")
        self.assertEqual(waiting["blocked_by_run_id"], "br_fake_app")
        scheduler.finish("br_fake_app", "COMPLETED", finished_at="2026-01-01T00:00:01+00:00")
        from p4_codex_bridge._exec_dispatch import dispatch
        dispatch(self.bridge.registry.path)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and scheduler.get(exec_run.bridge_run_id)["status"] not in scheduler.TERMINAL:
            time.sleep(0.05)
        self.assertEqual(scheduler.get(exec_run.bridge_run_id)["status"], "COMPLETED")

    def test_unicode_round_trip(self):
        result = self.run_model("unicode")
        self.assertTrue(result.ok)
        self.assertIn("café 🧪", result.content)

    def test_timeout_is_recorded_and_process_stops(self):
        result = self.run_model("timeout", timeout_seconds=0.3)
        self.assertFalse(result.ok)
        record = self.bridge.status(result.bridge_run_id)
        self.assertEqual(record.status, RunStatus.TIMED_OUT)

    def test_exit_nonzero_has_redacted_stderr(self):
        result = self.run_model("nonzero")
        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 7)
        self.assertNotIn("abc123", result.stderr)

    def test_missing_chatgpt_auth_is_structured(self):
        result = self.run_model("auth")
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "CODEX_AUTH_REQUIRED")

    def test_empty_response_is_error(self):
        result = self.run_model("empty")
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "CODEX_EMPTY_RESPONSE")

    def test_structured_output_is_parsed(self):
        result = self.run_model("schema", output_schema={"type": "object", "properties": {"answer": {"type": "string"}}})
        self.assertTrue(result.ok)
        self.assertEqual(result.structured_output, {"answer": "ok"})
        self.assertFalse(list((self.state / "temp").glob("*.json")))

    def test_structured_output_rejects_invalid_json_without_repair(self):
        result = self.run_model("bad-json", output_schema={"type": "object"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "STRUCTURED_OUTPUT_INVALID")
        self.assertEqual(result.content, "not-json")

    def test_codex_schema_rejection_is_a_provider_failure(self):
        result = self.run_model("schema-reject", output_schema={"type": 12})
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "CODEX_EXIT_NONZERO")

    def test_output_last_message_is_read_and_cleaned(self):
        result = self.bridge.run("hello", cwd=self.cwd, model="schema", capture_last_message=True,
                                 output_schema={"type": "object"})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.content, '{"answer": "ok"}')
        self.assertFalse(list((self.state / "temp").glob("*.txt")))

    def test_output_last_message_missing_and_malformed_are_errors(self):
        missing = self.run_model("last-missing", capture_last_message=True)
        malformed = self.run_model("last-malformed", capture_last_message=True, output_schema={"type": "object"})
        self.assertEqual(missing.error["code"], "OUTPUT_LAST_MESSAGE_MISSING")
        self.assertEqual(malformed.error["code"], "STRUCTURED_OUTPUT_INVALID")
        self.assertFalse(list((self.state / "temp").glob("*.txt")))

    def test_output_last_message_timeout_cleans_temp(self):
        result = self.run_model("timeout", timeout_seconds=0.2, capture_last_message=True)
        self.assertEqual(result.error["code"], "CODEX_TIMEOUT")
        self.assertFalse(list((self.state / "temp").glob("*.txt")))

    def test_secret_redaction_in_structured_output(self):
        result = self.run_model("secret", output_schema={"type": "object"})
        self.assertEqual(result.structured_output["access_token"], "[REDACTED]")
        self.assertNotIn("do-not-leak", result.content)
        self.assertNotIn("abc.def", result.content)

    def test_cwd_must_be_absolute_existing_directory_and_allowed(self):
        with self.assertRaises(ValueError):
            self.bridge.start("x", cwd="relative")
        with self.assertRaises(ValueError):
            self.bridge.start("x", cwd=self.root / "missing")
        outside = Path(tempfile.gettempdir())
        with self.assertRaises(ValueError):
            self.bridge.start("x", cwd=outside)

    def test_analysis_profile_and_permission_mapping(self):
        result = self.bridge.run("x", cwd=self.cwd, permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER))
        self.assertTrue(result.ok)
        run = self.bridge.list_runs()[0]
        self.assertEqual(run.profile, "analysis")
        self.assertEqual(run.backend, "codex-exec")
        args_result = self.run_model("args")
        args = json.loads(args_result.content.removeprefix("got:"))
        self.assertIn("--sandbox", args)
        self.assertIn("read-only", args)
        self.assertIn("--ask-for-approval", args)
        self.assertIn("never", args)
        self.assertIn("--ignore-user-config", args)

    def test_unimplemented_profiles_rejected(self):
        with self.assertRaisesRegex(ValueError, "planned"):
            self.bridge.start("x", cwd=self.cwd, profile="implementation")

    def test_invalid_timeout_model_effort_and_config(self):
        for kwargs in (
            {"timeout_seconds": 0},
            {"model": "bad model"},
            {"reasoning_effort": ""},
            {"config_policy": "explicit"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.bridge.start("x", cwd=self.cwd, **kwargs)

    def test_exec_resume_requires_explicit_inherited_permissions_and_parses_result(self):
        with self.assertRaisesRegex(ValueError, "confirm_inherited_permissions"):
            self.bridge.resume("fake-session-123", "continue", cwd=self.cwd)
        result = self.bridge.resume(
            "fake-session-123", "continue", cwd=self.cwd,
            confirm_inherited_permissions=True,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.session_id, "fake-session-123")
        self.assertEqual(self.bridge.list_runs()[0].backend, "codex-exec-resume")

    def test_exec_resume_rejects_unsafe_id_and_reports_process_failure(self):
        with self.assertRaises(ValueError):
            self.bridge.resume("--help", "continue", cwd=self.cwd, confirm_inherited_permissions=True)
        result = self.bridge.resume(
            "fake-session-123", "continue", cwd=self.cwd, model="nonzero",
            confirm_inherited_permissions=True,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "CODEX_EXIT_NONZERO")
        timeout = self.bridge.resume(
            "fake-session-123", "continue", cwd=self.cwd, model="timeout",
            timeout_seconds=0.2, confirm_inherited_permissions=True,
        )
        self.assertEqual(timeout.error["code"], "CODEX_TIMEOUT")

    def test_exec_fork_preserves_thread_id_output(self):
        result = self.bridge.fork(
            "fake-session-123", "branch", cwd=self.cwd,
            confirm_inherited_permissions=True,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.session_id, "fake-session-123")
        self.assertEqual(self.bridge.list_runs()[0].backend, "codex-exec-fork")

    def test_exec_review_requires_one_supported_target(self):
        with self.assertRaisesRegex(ValueError, "exactly one target"):
            self.bridge.review(cwd=self.cwd)
        result = self.bridge.review(cwd=self.cwd, uncommitted=True, instructions="Only inspect.")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.bridge.list_runs()[0].backend, "codex-exec-review")

    def test_permissions_reject_invalid_values_and_validate_roots(self):
        with self.assertRaises(ValueError):
            self.bridge.start("x", cwd=self.cwd, permissions=CodexPermissions(sandbox="invalid"))
        with self.assertRaises(ValueError):
            self.bridge.start("x", cwd=self.cwd, permissions=CodexPermissions(
                sandbox=SandboxMode.WORKSPACE_WRITE, writable_roots=(self.root / "missing",),
            ))
        with self.assertRaisesRegex(ValueError, "explicit on-request"):
            self.bridge.start("x", cwd=self.cwd, permissions=CodexPermissions(
                sandbox=SandboxMode.FULL_ACCESS, approval_policy=ApprovalPolicy.NEVER,
            ))

    def test_workspace_write_network_defaults_to_disabled(self):
        result = self.bridge.run("inspect", cwd=self.cwd, model="args", permissions=CodexPermissions(
            sandbox=SandboxMode.WORKSPACE_WRITE, approval_policy=ApprovalPolicy.ON_REQUEST,
        ))
        args = json.loads(result.content.removeprefix("got:"))
        self.assertIn('sandbox_workspace_write.network_access=false', args)

    def test_config_policy_and_typed_override_conflicts(self):
        with self.assertRaisesRegex(ValueError, "required for explicit"):
            self.bridge.start("x", cwd=self.cwd, config_policy="explicit")
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.bridge.start("x", cwd=self.cwd, config_policy="explicit", reasoning_effort="low",
                              config_overrides={"model_reasoning_effort": "high"})

    def test_process_registry_list_status_and_result_cleanup(self):
        run = self.bridge.start("inspect", cwd=self.cwd)
        self.assertIn(run.status, {RunStatus.STARTING, RunStatus.RUNNING})
        seen = {item.bridge_run_id for item in self.bridge.list_runs()}
        self.assertIn(run.bridge_run_id, seen)
        deadline = time.monotonic() + 5
        while self.bridge.status(run.bridge_run_id).status in {RunStatus.STARTING, RunStatus.RUNNING} and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.bridge.status(run.bridge_run_id).status, RunStatus.COMPLETED)
        result = self.bridge.read_result(run.bridge_run_id)
        self.assertTrue(result.ok)
        self.assertIsNone(self.bridge.read_result(run.bridge_run_id))

    def test_run_discovery_metadata_inspect_and_native_id_resolution(self):
        result = self.bridge.run("metadata discovery", cwd=self.cwd, metadata={
            "agent_name": "RequirementAnalysisAgent", "agent_role": "planning", "task_key": "P4-123",
            "project": "P4-Planning-Agent", "token": "secret-value",
        })
        self.assertTrue(result.ok)
        self.assertTrue(result.bridge_run_id.startswith("br_"))
        rows = self.bridge.discover_runs(task="P4-123", agent="RequirementAnalysisAgent")
        self.assertEqual(len(rows), 1)
        snapshot = self.bridge.inspect(result.bridge_run_id)
        self.assertEqual(snapshot["status"], "COMPLETED")
        self.assertEqual(snapshot["session_id"], "fake-session-123")
        self.assertEqual(snapshot["agent_name"], "RequirementAnalysisAgent")
        self.assertNotIn("secret-value", json.dumps(snapshot))
        by_native = self.bridge.resolve_run_reference("fake-session-123")
        self.assertEqual(by_native["bridge_run_id"], result.bridge_run_id)
        events = list(self.bridge.watch(result.bridge_run_id))
        self.assertIn("AgentMessageCompleted", [event["type"] for event in events])
        self.assertGreaterEqual(len(list(self.bridge.watch(result.bridge_run_id))), len(events))
        other = self.bridge.run("other run in same native session", cwd=self.cwd)
        own_events = list(self.bridge.watch(result.bridge_run_id))
        other_events = list(self.bridge.watch(other.bridge_run_id))
        self.assertEqual(len([e for e in own_events if e["type"] == "AgentMessageCompleted"]), 1)
        self.assertEqual(len([e for e in other_events if e["type"] == "AgentMessageCompleted"]), 1)

    def test_native_reference_ambiguity_is_not_silently_resolved(self):
        first = self.bridge.run("first", cwd=self.cwd)
        self.bridge.run("second", cwd=self.cwd)
        self.assertTrue(first.ok)
        with self.assertRaisesRegex(ValueError, "ambiguous run reference"):
            self.bridge.resolve_run_reference("fake-session-123")

    def test_watch_task_selector_requires_unique_active_run(self):
        with self.assertRaisesRegex(ValueError, "matched 0 active runs"):
            list(self.bridge.watch(task="P4-404", follow=True))

    def test_running_inspect_and_task_watch_are_read_only(self):
        run = self.bridge.start("long run", cwd=self.cwd, model="timeout", metadata={"agent_name": "SlowAgent", "task_key": "P4-9"})
        try:
            snapshot = self.bridge.inspect(run.bridge_run_id)
            self.assertIn(snapshot["status"], {"STARTING", "RUNNING"})
            events = list(self.bridge.watch(task="P4-9", follow=False))
            self.assertIn("RunStatus", [event["type"] for event in events])
            self.assertIn(self.bridge.inspect(run.bridge_run_id)["status"], {"STARTING", "RUNNING"})
        finally:
            self.bridge.stop(run.bridge_run_id, timeout_seconds=2)

    def test_invalid_run_reference_is_clear(self):
        with self.assertRaisesRegex(KeyError, "no managed run found"):
            self.bridge.resolve_run_reference("does-not-exist")

    def test_stop_managed_run(self):
        run = self.bridge.start("stop", cwd=self.cwd, model="timeout", timeout_seconds=20)
        deadline = time.monotonic() + 5
        while self.bridge.status(run.bridge_run_id).pid is None and time.monotonic() < deadline:
            time.sleep(0.05)
        stopped = self.bridge.stop(run.bridge_run_id, timeout_seconds=5)
        self.assertEqual(stopped.status, RunStatus.STOPPED)

    def test_kill_only_registered_run_tree(self):
        run = self.bridge.start("kill", cwd=self.cwd, model="timeout", timeout_seconds=20)
        deadline = time.monotonic() + 5
        while self.bridge.status(run.bridge_run_id).pid is None and time.monotonic() < deadline:
            time.sleep(0.05)
        result = self.bridge.kill(run.bridge_run_id)
        self.assertEqual(result.status, RunStatus.STOPPED)

    def test_orphan_detection_uses_registry_identity(self):
        run_id = "orphan-test"
        self.bridge.registry.create(
            run_id,
            backend="codex-exec",
            cwd=str(self.cwd),
            model=None,
            profile="analysis",
            result_path=str(self.state / "results" / "orphan-test.json"),
        )
        self.bridge.registry.update(
            run_id,
            worker_pid=2_147_483_647,
            worker_identity="no-such-process",
            status=RunStatus.RUNNING.value,
        )
        self.assertEqual(self.bridge.status(run_id).status, RunStatus.ORPHANED)

    def test_models_are_discovered_using_app_server(self):
        models = self.bridge.list_models()
        self.assertEqual(models[0]["model"], "fake-model")

    def test_capabilities_version(self):
        self.assertEqual(self.bridge.get_version(), "codex-cli fake-1.0")
        capabilities = self.bridge.get_capabilities()
        self.assertTrue(capabilities["exec"]["output_schema"])
        self.assertTrue(capabilities["app_server"]["available"])

    def test_config_mcp_skills_and_effective_state_are_separate(self):
        config = self.bridge.get_effective_config(cwd=self.cwd)
        self.assertEqual(config["values"]["model"], "fake-model")
        self.assertNotIn("api_key", config["values"])
        self.assertEqual(config["sources"]["model"], "project")
        servers = self.bridge.list_configured_mcps(cwd=self.cwd)
        self.assertEqual(servers[0]["tool_count"], 1)
        self.assertIsNone(servers[0]["callable"])
        self.assertIsNone(servers[0]["effective_for_run"])
        skills = self.bridge.list_effective_skills(cwd=self.cwd)
        self.assertEqual(skills[0]["name"], "fixture-skill")
        self.assertTrue(skills[0]["child_visible"])
        self.assertEqual(skills[0]["child_context"], "diagnostic_app_server")
        effective = self.bridge.get_effective_capabilities(cwd=self.cwd)
        self.assertIsNone(effective["effective"]["mcp"]["effective_for_run"])
        self.assertEqual(effective["effective"]["cwd"], str(self.cwd.resolve()))

    def test_binary_not_found(self):
        with patch.dict(os.environ, {"CODEX_BIN": str(self.root / "absent.py")}):
            result = self.bridge.run("hello", cwd=self.cwd)
        self.assertFalse(result.ok)
        self.assertIn("not found", result.error["message"].lower())

    def test_registry_does_not_store_prompt_or_environment(self):
        result = self.bridge.run("CONFIDENTIAL_PROMPT_123", cwd=self.cwd)
        with closing(sqlite3.connect(self.state / "runs.sqlite3")) as db:
            rows = db.execute("select * from runs").fetchall()
        self.assertNotIn("CONFIDENTIAL_PROMPT_123", repr(rows))
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
