from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from p4_codex_bridge import CodexRuntimeManager, RuntimeState, TurnState
from p4_codex_bridge.registry import RunRegistry


FAKE_SERVER = r'''
import json,sys
thread="t-runtime"
for line in sys.stdin:
 m=json.loads(line); method=m.get("method"); i=m.get("id")
 if method=="initialize":
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"protocolVersion":"v2","serverInfo":{"name":"fake"}}}),flush=True)
 elif method=="thread/start":
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"thread":{"id":thread}}}),flush=True)
 elif method=="turn/start":
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"turn":{"id":"turn-1"}}}),flush=True)
  p={"threadId":thread,"turnId":"turn-1"}
  print(json.dumps({"jsonrpc":"2.0","method":"turn/started","params":p}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"item/started","params":{**p,"item":{"id":"user-item","type":"userMessage"}}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"item/completed","params":{**p,"item":{"id":"user-item","type":"userMessage"}}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"item/started","params":{**p,"item":{"id":"agent-item","type":"agentMessage"}}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"item/agentMessage/delta","params":{**p,"delta":"OK"}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"item/completed","params":{**p,"item":{"id":"agent-item","type":"agentMessage","text":"OK"}}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"turn/completed","params":{**p,"turn":{"status":"completed"}}}),flush=True)
 elif method=="initialized": pass
'''


class RuntimeManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = CodexRuntimeManager(cwd=self.root, database_path=self.root / "bridge.sqlite",
            lock_path=self.root / "runtime.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER])

    def tearDown(self):
        self.manager.stop(mode="FORCE")
        self.temp.cleanup()

    def test_server_thread_turn_health_and_metrics(self):
        health = self.manager.start()
        self.assertEqual(health["status"], RuntimeState.HEALTHY)
        thread = self.manager.create_thread(metadata={"agent_name": "TestAgent", "task_key": "P4-7"})
        self.assertEqual(thread.thread_id, "t-runtime")
        turn = self.manager.start_turn(thread.thread_id, "Reply OK", metadata={"agent_role": "validation"}, access_mode="WRITE")
        self.assertEqual(turn.turn_id, "turn-1")
        # Reader is asynchronous; poll the fake protocol's terminal notification.
        import time
        deadline = time.monotonic() + 2
        while turn.status not in {TurnState.COMPLETED, TurnState.FAILED} and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(turn.status, TurnState.COMPLETED)
        self.assertEqual(turn.final_text, "OK")
        observed_types = [event["type"] for event in turn.events]
        self.assertIn("ItemStarted", observed_types)
        self.assertIn("AgentMessageCompleted", observed_types)
        self.assertNotIn("ToolStarted", observed_types)
        self.assertNotIn("ToolCompleted", observed_types)
        deadline = time.monotonic() + 2
        while self.manager.inspect(turn.bridge_run_id)["status"] != "COMPLETED" and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.manager.get_metrics()["completed_turns"], 1)
        scheduled = self.manager.inspect(turn.bridge_run_id)
        self.assertEqual(scheduled["status"], "COMPLETED")
        self.assertEqual(scheduled["access_mode"], "WRITE")
        self.assertIsNone(scheduled["queue_position"])
        self.assertEqual(self.manager.get_resource_status()["workspace_locks"], [])
        registry = RunRegistry(self.root / "bridge.sqlite")
        row = registry.discover(task="P4-7", agent="TestAgent")[0]
        self.assertEqual(row["bridge_run_id"], turn.bridge_run_id)
        self.assertEqual(registry.resolve_reference(turn.thread_id)["bridge_run_id"], turn.bridge_run_id)
        self.assertEqual(registry.resolve_reference(turn.turn_id)["bridge_run_id"], turn.bridge_run_id)
        import time
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            observed = registry.events_for(row)
            event_types = [event.get("type") for event in observed]
            if "RESOURCE_RELEASED" in event_types and "TurnCompleted" in event_types:
                break
            time.sleep(0.01)
        first_watch = registry.events_for(row)
        second_watch = registry.events_for(registry.inspect(turn.bridge_run_id))
        self.assertEqual(first_watch, second_watch)
        event_types = [event["type"] for event in first_watch]
        self.assertIn("TurnStarted", event_types)
        self.assertIn("AgentMessageDelta", event_types)
        self.assertIn("TurnCompleted", event_types)
        self.assertEqual(event_types.count("RESOURCE_RELEASED"), 1)
        inspected = registry.inspect(turn.bridge_run_id)
        self.assertEqual(inspected["server_id"], self.manager.instance_id)
        self.assertEqual(inspected["agent_role"], "validation")
        self.assertTrue(inspected["process_identity"])

    def test_lifecycle_events_without_turn_id_are_attached_to_active_turn(self):
        server = FAKE_SERVER.replace('p={"threadId":thread,"turnId":"turn-1"}', 'p={"threadId":thread}')
        manager = CodexRuntimeManager(cwd=self.root, database_path=self.root / "missing-turn-id.sqlite",
            lock_path=self.root / "missing-turn-id.lock", command=[sys.executable, "-u", "-c", server])
        try:
            manager.start()
            thread = manager.create_thread()
            turn = manager.start_turn(thread.thread_id, "Reply OK")
            import time
            deadline = time.monotonic() + 2
            while turn.status not in {TurnState.COMPLETED, TurnState.FAILED} and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(turn.status, TurnState.COMPLETED)
            registry = RunRegistry(self.root / "missing-turn-id.sqlite")
            deadline = time.monotonic() + 2
            events = registry.events_for(registry.inspect(turn.bridge_run_id))
            while "TurnCompleted" not in [event["type"] for event in events] and time.monotonic() < deadline:
                time.sleep(.01)
                events = registry.events_for(registry.inspect(turn.bridge_run_id))
            types = [event["type"] for event in events]
            self.assertIn("TurnStarted", types)
            self.assertIn("TurnCompleted", types)
            self.assertIn("AgentMessageDelta", types)
            self.assertTrue(all(event.get("turn_id") == turn.turn_id for event in events if event["type"] in {"TurnStarted", "TurnCompleted", "AgentMessageDelta"}))
        finally:
            manager.stop(mode="FORCE")

    def test_singleton_and_idempotent_start(self):
        self.manager.start()
        self.assertEqual(self.manager.start()["status"], "HEALTHY")
        other = CodexRuntimeManager(cwd=self.root, database_path=self.root / "other.sqlite",
            lock_path=self.root / "runtime.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER])
        try:
            with self.assertRaisesRegex(RuntimeError, "singleton lock"):
                other.start()
        finally:
            other.stop(mode="FORCE")

    def test_state_machine_rejects_invalid_transition(self):
        from p4_codex_bridge.runtime_manager import ManagedTurn
        turn = ManagedTurn("x", "t", TurnState.CREATED, "now")
        with self.assertRaisesRegex(ValueError, "invalid turn transition"):
            self.manager._transition(turn, TurnState.COMPLETED)

    def test_registry_schema_and_dry_run_recovery(self):
        self.manager._db("INSERT INTO runtime_turns(turn_id,thread_id,status,started_at) VALUES('r','t','RUNNING','now')")
        report = self.manager.recover(dry_run=True)
        self.assertEqual(report["actions"][0]["classification"], "UNKNOWN")
        self.assertTrue(report["dry_run"])

    def test_startup_recovery_marks_unverified_turn_unknown_and_replays_journal(self):
        self.manager._db("INSERT INTO runtime_turns(turn_id,thread_id,status,started_at,bridge_run_id) VALUES('orphan-turn','orphan-thread','RUNNING','now','br_orphan')")
        self.manager._db("INSERT INTO runtime_events(thread_id,turn_id,event_type,created_at,payload_json) VALUES('orphan-thread','orphan-turn','TurnStarted','2026-01-01T00:00:00+00:00','{\"type\":\"TurnStarted\"}')")
        self.manager.start()
        registry = RunRegistry(self.root / "bridge.sqlite")
        row = registry.resolve_reference("br_orphan")["run"]
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertEqual(registry.events_for(row)[0]["type"], "TurnStarted")

    def test_unknown_registry_schema_fails_closed(self):
        import sqlite3
        from contextlib import closing
        path = self.root / "future.sqlite"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE bridge_schema(version INTEGER NOT NULL)")
            db.execute("INSERT INTO bridge_schema VALUES(99)")
        with self.assertRaisesRegex(RuntimeError, "unsupported bridge registry schema"):
            CodexRuntimeManager(cwd=self.root, database_path=path, command=[sys.executable, "-c", "pass"])

    def test_runtime_sqlite_teardown_repeated_immediate_delete(self):
        import shutil
        for index in range(6):
            state = self.root / f"teardown-{index}"
            state.mkdir()
            manager = CodexRuntimeManager(cwd=self.root, database_path=state / "bridge.sqlite",
                lock_path=state / "runtime.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER])
            manager.start()
            thread = manager.create_thread()
            turn = manager.start_turn(thread.thread_id, "finish immediately")
            import time
            deadline = time.monotonic() + 2
            while turn.status not in {TurnState.COMPLETED, TurnState.FAILED} and time.monotonic() < deadline:
                time.sleep(0.01)
            manager.stop(mode="FORCE")
            self.assertFalse(manager._control_thread.is_alive())
            shutil.rmtree(state)
            self.assertFalse(state.exists())

    def test_control_worker_retries_transient_sqlite_lock(self):
        import sqlite3
        import time
        from contextlib import closing
        self.manager.start()
        with closing(sqlite3.connect(self.root / "bridge.sqlite", timeout=1)) as db:
            db.execute("BEGIN EXCLUSIVE")
            time.sleep(2.2)
            db.rollback()
        time.sleep(.15)
        self.assertIsNotNone(self.manager._control_thread)
        self.assertTrue(self.manager._control_thread.is_alive())

    def test_registry_schema_initialization_is_serialized_across_workers(self):
        from concurrent.futures import ThreadPoolExecutor
        from p4_codex_bridge.registry import RunRegistry
        database = self.root / "parallel-schema.sqlite"
        with ThreadPoolExecutor(max_workers=8) as pool:
            registries = list(pool.map(lambda _index: RunRegistry(database), range(16)))
        self.assertEqual(len(registries), 16)
        self.assertEqual(RunRegistry(database).list(), [])

    def test_exec_release_notifies_manager_to_dispatch_waiting_app_server_turn(self):
        from p4_codex_bridge.runtime_manager import notify_app_server_capacity_change
        scheduler = self.manager.scheduler
        scheduler.submit(turn_id="exec-turn", thread_id="exec-thread", backend="exec", profile="analysis",
            workspace=self.root, prompt="fake exec", access_mode="READ", bridge_run_id="br_exec_fake",
            submitted_at="2026-01-01T00:00:00+00:00")
        scheduler.dispatch(backend="exec")
        self.manager.start()
        thread = self.manager.create_thread()
        turn = self.manager.start_turn(thread.thread_id, "app waits for exec slot")
        self.assertEqual(turn.status, TurnState.WAITING_FOR_SLOT)
        scheduler.finish("br_exec_fake", "COMPLETED", finished_at="2026-01-01T00:00:01+00:00")
        notify_app_server_capacity_change(self.root / "bridge.sqlite")
        import time
        deadline = time.monotonic() + 3
        while turn.status not in {TurnState.COMPLETED, TurnState.FAILED} and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(turn.status, TurnState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
