from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from p4_codex_bridge import ApprovalError, ApprovalHandlingPolicy, ApprovalPolicy, CodexBridge, CodexPermissions, SandboxMode
from p4_codex_bridge.events import EventDecodeError, EventNormalizer, EventSubscription, decode_json_line
from p4_codex_bridge.registry import RunRegistry


FAKE_APP_SERVER = r'''import json, sys, time
args=sys.argv[1:]
if args == ["--version"]: print("codex fake-app")
elif args == ["--help"]: print("Usage: codex app-server exec")
elif args == ["exec", "--help"]: print("Usage: codex exec --json --model --sandbox --ask-for-approval -C")
elif args == ["app-server", "--help"]: print("Usage: codex app-server --listen stdio:// (experimental)")
elif args[:2] == ["app-server", "--listen"]:
  base=__import__('os').path.basename(__import__('os').getcwd())
  thread_id="thread-"+base; turn_id="turn-"+base
  for line in sys.stdin:
    m=json.loads(line); method=m.get("method"); i=m.get("id")
    if method == "initialize":
      print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"protocolVersion":"v2"}}),flush=True)
    elif method == "thread/start":
      print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"thread":{"id":thread_id}}}),flush=True)
    elif method == "turn/start":
      print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"turn":{"id":turn_id}}}),flush=True)
      params={"threadId":thread_id,"turnId":turn_id}
      print(json.dumps({"jsonrpc":"2.0","method":"turn/started","params":{**params,"turn":{"id":turn_id,"status":"inProgress"}}}),flush=True)
      if __import__('os').path.basename(__import__('os').getcwd()).startswith('slow-workspace'):
        interrupt=json.loads(sys.stdin.readline())
        print(json.dumps({"jsonrpc":"2.0","id":interrupt['id'],"result":{}}),flush=True)
        print(json.dumps({"jsonrpc":"2.0","method":"turn/completed","params":{**params,"turn":{"id":turn_id,"status":"interrupted"}}}),flush=True)
        continue
      if __import__('os').path.basename(__import__('os').getcwd()) == 'crash-workspace':
        sys.exit(7)
      if "APPROVAL" in str(m):
        pass
      # The tests select approval mode by setting P4_FAKE_APPROVAL.
      if __import__('os').getcwd().endswith('approval-workspace'):
        print(json.dumps({"jsonrpc":"2.0","id":99,"method":"item/commandExecution/requestApproval","params":{**params,"itemId":"item-1","startedAtMs":1,"command":"echo safe","reason":"test"}}),flush=True)
        response=json.loads(sys.stdin.readline())
        assert response.get("result",{}).get("decision") in {"accept", "decline", "cancel"}
      for method, p in [
        ("item/agentMessage/delta",{**params,"itemId":"msg-1","delta":"O"}),
        ("item/agentMessage/delta",{**params,"itemId":"msg-1","delta":"K"}),
        ("item/completed",{**params,"completedAtMs":2,"item":{"id":"msg-1","type":"agentMessage","text":"OK"}}),
        ("turn/completed",{**params,"turn":{"id":turn_id,"status":"completed"}})]:
        print(json.dumps({"jsonrpc":"2.0","method":method,"params":p,"emittedAtMs":1000}),flush=True)
    elif method == "turn/interrupt":
      print(json.dumps({"jsonrpc":"2.0","id":i,"result":{}}),flush=True)
'''


class EventNormalizationTests(unittest.TestCase):
    def test_deltas_assemble_unicode_and_completed_text(self):
        normalizer = EventNormalizer()
        a = normalizer.normalize({"method":"item/agentMessage/delta","params":{"threadId":"t","turnId":"u","itemId":"i","delta":"caf"}})
        b = normalizer.normalize({"method":"item/agentMessage/delta","params":{"threadId":"t","turnId":"u","itemId":"i","delta":"é 🧪"}})
        done = normalizer.normalize({"method":"item/completed","params":{"threadId":"t","turnId":"u","completedAtMs":3,"item":{"id":"i","type":"agentMessage","text":"café 🧪"}}})
        self.assertEqual(a.sequence, 1); self.assertEqual(b.data["partial_text"], "café 🧪")
        self.assertEqual(done.type, "AgentMessageCompleted"); self.assertEqual(done.data["final_text"], "café 🧪")

    def test_unknown_event_is_preserved(self):
        event = EventNormalizer().normalize({"method":"future/event","params":{"threadId":"t","x":1}})
        self.assertEqual(event.type, "UnknownEvent"); self.assertEqual(event.raw_event["method"], "future/event")

    def test_turn_failure_and_interruption_are_distinct(self):
        normalizer = EventNormalizer()
        failed = normalizer.normalize({"method":"turn/completed","params":{"threadId":"t","turn":{"id":"u","status":"failed"}}})
        interrupted = normalizer.normalize({"method":"turn/completed","params":{"threadId":"t","turn":{"id":"v","status":"interrupted"}}})
        self.assertEqual(failed.type, "TurnFailed")
        self.assertEqual(interrupted.type, "TurnInterrupted")

    def test_tool_lifecycle_is_normalized_with_duration_and_summary(self):
        normalizer = EventNormalizer()
        started = normalizer.normalize({"method":"item/started","params":{"threadId":"t","turnId":"u","startedAtMs":100,"item":{"id":"tool-1","type":"commandExecution","command":"echo ok"}}})
        completed = normalizer.normalize({"method":"item/completed","params":{"threadId":"t","turnId":"u","completedAtMs":135,"item":{"id":"tool-1","type":"commandExecution","status":"completed","aggregatedOutput":"ok"}}})
        self.assertEqual(started.type, "ToolStarted")
        self.assertEqual(completed.type, "ToolCompleted")
        self.assertEqual(completed.data["duration_ms"], 35)
        self.assertEqual(completed.data["result_summary"], "ok")

    def test_message_items_are_not_reported_as_tools_but_schema_tool_items_are(self):
        normalizer = EventNormalizer()
        for item_type in ("userMessage", "agentMessage", "plan", "reasoning", "subAgentActivity"):
            started = normalizer.normalize({"method":"item/started","params":{"threadId":"t","turnId":"u","item":{"id":item_type,"type":item_type}}})
            self.assertEqual(started.type, "ItemStarted", item_type)
        for item_type in ("commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "collabAgentToolCall", "webSearch", "imageView", "imageGeneration"):
            started = normalizer.normalize({"method":"item/started","params":{"threadId":"t","turnId":"u","item":{"id":item_type,"type":item_type}}})
            self.assertEqual(started.type, "ToolStarted", item_type)

    def test_malformed_json_and_event_are_rejected(self):
        with self.assertRaises(EventDecodeError): decode_json_line("{")
        with self.assertRaises(EventDecodeError): EventNormalizer().normalize({"params":{}})

    def test_critical_events_are_not_dropped_when_queue_full(self):
        sub = EventSubscription(maxsize=1)
        from p4_codex_bridge import CodexEvent
        sub.publish(CodexEvent("AgentMessageDelta", "", sequence=1))
        producer = threading.Thread(target=lambda: sub.publish(CodexEvent("TurnCompleted", "", sequence=2)))
        producer.start(); time.sleep(0.05); self.assertTrue(producer.is_alive())
        sub.queue.get_nowait(); producer.join(timeout=1)
        self.assertFalse(producer.is_alive()); self.assertEqual(sub.queue.get_nowait().type, "TurnCompleted")
        sub.close()

    def test_filtering_unsubscribe_and_noncritical_overflow(self):
        from p4_codex_bridge import CodexEvent
        sub = EventSubscription(maxsize=2, thread_id="wanted", turn_id="turn")
        sub.publish(CodexEvent("AgentMessageDelta", "", thread_id="other", turn_id="turn"))
        for n in range(10): sub.publish(CodexEvent("AgentMessageDelta", "", thread_id="wanted", turn_id="turn", sequence=n))
        self.assertEqual(sub.dropped, 8)
        self.assertEqual(sub.queue.qsize(), 2)
        sub.queue.get_nowait(); sub.queue.get_nowait()
        sub.close()
        self.assertEqual(list(sub), [])

    def test_event_throughput_has_bounded_memory(self):
        from p4_codex_bridge import CodexEvent
        sub = EventSubscription(maxsize=64)
        started = time.monotonic()
        for n in range(5000): sub.publish(CodexEvent("AgentMessageDelta", "", sequence=n))
        duration = time.monotonic() - started
        self.assertLess(duration, 3)
        self.assertEqual(sub.queue.qsize(), 64)
        self.assertEqual(sub.dropped, 5000 - 64)
        sub.close()

    def test_event_data_redacts_secret_fields(self):
        event = EventNormalizer().normalize({"method":"future/event","params":{"access_token":"sensitive-value","reason":"Bearer abc.def"}})
        self.assertEqual(event.data["access_token"], "[REDACTED]")
        self.assertNotIn("abc.def", json.dumps(event.to_dict()))

    def test_token_usage_counters_remain_visible_but_not_auth_secrets(self):
        event = EventNormalizer().normalize({"method":"thread/tokenUsage/updated","params":{"threadId":"t","turnId":"u","tokenUsage":{"last":{"inputTokens":12,"outputTokens":3,"totalTokens":15,"cachedInputTokens":0,"reasoningOutputTokens":1},"total":{"inputTokens":12,"outputTokens":3,"totalTokens":15,"cachedInputTokens":0,"reasoningOutputTokens":1},"modelContextWindow":1000}}})
        self.assertEqual(event.type, "TokenUsageUpdated")
        self.assertEqual(event.data["tokenUsage"]["total"]["totalTokens"], 15)

    def test_database_migration_preserves_existing_runs_and_adds_event_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "runs.sqlite3"
            import sqlite3
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE runs (bridge_run_id TEXT PRIMARY KEY, pid INTEGER, worker_pid INTEGER, pid_identity TEXT, worker_identity TEXT, backend TEXT NOT NULL, cwd TEXT NOT NULL, model TEXT, profile TEXT NOT NULL, started_at TEXT NOT NULL, status TEXT NOT NULL, exit_code INTEGER, last_error TEXT)")
                connection.execute("INSERT INTO runs VALUES('old',NULL,NULL,NULL,NULL,'codex-exec','C:/safe',NULL,'analysis','now','COMPLETED',0,NULL)")
            connection.close()
            registry = RunRegistry(db)
            with sqlite3.connect(db) as connection:
                self.assertEqual(connection.execute("SELECT bridge_run_id FROM runs").fetchone()[0], "old")
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            connection.close()
            self.assertTrue({"turn_events", "approvals"}.issubset(tables))


class FakeAppServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p4-event-test-")
        self.root = Path(self.temp.name); self.cwd = self.root / "workspace"; self.cwd.mkdir()
        self.fake = self.root / "fake_codex.py"; self.fake.write_text(FAKE_APP_SERVER, encoding="utf-8")
        self.env = patch.dict(os.environ, {"CODEX_BIN": str(self.fake)}); self.env.start()
        self.bridge = CodexBridge(state_dir=self.root / "state", allowed_roots=(self.root,))

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def test_turn_stream_and_lifecycle_persistence(self):
        turn = self.bridge.start_turn("reply", cwd=self.cwd)
        try:
            events = list(turn.events(timeout=5))
            types = [event.type for event in events]
            self.assertEqual(types[:3], ["TurnStarted", "AgentMessageDelta", "AgentMessageDelta"])
            self.assertIn("AgentMessageCompleted", types); self.assertEqual(types[-1], "TurnCompleted")
            self.assertEqual(turn.final_text, "OK")
            saved = self.bridge.get_events(turn_id=turn.turn_id)
            self.assertEqual([event["type"] for event in saved], ["TurnStarted", "TurnCompleted"])
        finally: turn.close()

    def test_manual_approval_can_be_resolved_through_registry(self):
        approval_cwd = self.root / "approval-workspace"; approval_cwd.mkdir()
        permissions = CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.ON_REQUEST)
        turn = self.bridge.start_turn("approve test", cwd=approval_cwd, permissions=permissions)
        try:
            subscription = turn.subscribe()
            found = None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try: event = subscription.queue.get(timeout=0.2)
                except Exception: continue
                if getattr(event, "type", None) == "ApprovalRequested": found = event; break
            self.assertIsNotNone(found)
            approval = found.data["approval"]["approval_id"]
            self.assertEqual(turn.status, "WAITING_APPROVAL")
            self.assertEqual(self.bridge.status(turn.turn_id)["status"], "WAITING_APPROVAL")
            self.assertEqual(self.bridge.list_managed()[0]["status"], "WAITING_APPROVAL")
            self.bridge.approve(approval)
            terminal = list(turn.events(timeout=5))
            self.assertEqual(terminal[-1].type, "TurnCompleted")
            self.assertEqual(self.bridge.list_pending_approvals(), [])
            with self.assertRaises(ApprovalError): self.bridge.approve(approval)
        finally: turn.close()

    def test_approval_timeout_rejects_and_does_not_approve(self):
        approval_cwd = self.root / "approval-workspace"; approval_cwd.mkdir()
        permissions = CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.ON_REQUEST)
        turn = self.bridge.start_turn("timeout approval", cwd=approval_cwd, permissions=permissions, approval_timeout_seconds=0.15)
        try:
            events = list(turn.events(timeout=5))
            resolved = next(event for event in events if event.type == "ApprovalResolved")
            self.assertEqual(resolved.data["decision"], "decline")
            self.assertIn("approval timeout", resolved.data["reason"])
            self.assertEqual(turn.status, "COMPLETED")
        finally: turn.close()

    def test_approval_timeout_error_policy_cancels_and_emits_error(self):
        approval_cwd = self.root / "approval-workspace"; approval_cwd.mkdir()
        permissions = CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.ON_REQUEST)
        turn = self.bridge.start_turn("timeout error", cwd=approval_cwd, permissions=permissions, approval_timeout_seconds=0.15, approval_timeout_policy="error")
        try:
            events = list(turn.events(timeout=5))
            error = next(event for event in events if event.type == "ServerError")
            self.assertEqual(error.data["code"], "APPROVAL_TIMEOUT")
            resolved = next(event for event in events if event.type == "ApprovalResolved")
            self.assertEqual(resolved.data["decision"], "cancel")
        finally: turn.close()

    def test_auto_reject_policy_never_approves(self):
        approval_cwd = self.root / "approval-workspace"; approval_cwd.mkdir()
        permissions = CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.ON_REQUEST)
        turn = self.bridge.start_turn("auto reject", cwd=approval_cwd, permissions=permissions, approval_handling_policy=ApprovalHandlingPolicy.AUTO_REJECT)
        try:
            events = list(turn.events(timeout=5))
            resolved = next(event for event in events if event.type == "ApprovalResolved")
            self.assertEqual(resolved.data["decision"], "decline")
        finally: turn.close()

    def test_full_access_requires_explicit_approval_policy(self):
        with self.assertRaises(ValueError):
            self.bridge.start_turn("x", cwd=self.cwd, permissions=CodexPermissions(SandboxMode.FULL_ACCESS, ApprovalPolicy.NEVER))

    def test_stream_disconnect_leaves_turn_available_for_interrupt(self):
        slow = self.root / "slow-workspace"; slow.mkdir()
        stream = self.bridge.stream_events("long turn", cwd=slow)
        started = next(event for event in stream if event.type == "TurnStarted")
        stream.close()
        turn = self.bridge.get_turn_handle(started.turn_id)
        self.assertEqual(turn.status, "RUNNING")
        turn.interrupt()
        events = list(turn.events(timeout=3))
        self.assertEqual(events[-1].type, "TurnInterrupted")
        turn.close()

    def test_close_persists_stopped_without_affecting_unmanaged_processes(self):
        slow = self.root / "slow-workspace"; slow.mkdir()
        turn = self.bridge.start_turn("stop me", cwd=slow)
        turn.close()
        self.assertEqual(turn.status, "STOPPED")
        self.assertEqual(self.bridge.get_turn_status(turn.turn_id), "STOPPED")

    def test_app_server_crash_is_normalized_and_persisted(self):
        crash = self.root / "crash-workspace"; crash.mkdir()
        turn = self.bridge.start_turn("crash", cwd=crash)
        try:
            events = list(turn.events(timeout=3))
            self.assertIn("APP_SERVER_CRASH", [event.data.get("code") for event in events if event.type == "ServerError"])
            self.assertEqual(self.bridge.get_turn_status(turn.turn_id), "FAILED")
        finally: turn.close()

    def test_async_stream_uses_same_normalized_events(self):
        async def collect():
            return [event async for event in self.bridge.astream_events("async reply", cwd=self.cwd, turn_timeout_seconds=5)]
        events = asyncio.run(collect())
        self.assertEqual(events[-1].type, "TurnCompleted")
        self.assertEqual(next(event for event in events if event.type == "AgentMessageCompleted").data["final_text"], "OK")

    def test_server_wide_stream_multiplexes_bridge_owned_turns(self):
        slow1 = self.root / "slow-workspace"; slow1.mkdir()
        slow2 = self.root / "slow-workspace-2"; slow2.mkdir()
        turn1 = self.bridge.start_turn("one", cwd=slow1)
        turn2 = self.bridge.start_turn("two", cwd=slow2)
        try:
            def interrupt_both():
                time.sleep(0.05)
                try:
                    turn1.interrupt(); turn2.interrupt()
                except Exception as exc:
                    interrupted.append(str(exc))
            interrupted = []
            worker = threading.Thread(target=interrupt_both); worker.start()
            events = list(self.bridge.stream_all_events(timeout=3))
            worker.join(timeout=3)
            self.assertGreaterEqual(sum(event.type == "TurnInterrupted" for event in events), 2, ([(event.type, event.turn_id) for event in events], interrupted, turn1.thread_id, turn1.turn_id, turn2.thread_id, turn2.turn_id))
        finally:
            turn1.close(); turn2.close()


if __name__ == "__main__": unittest.main()
