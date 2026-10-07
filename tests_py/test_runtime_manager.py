from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from p4_codex_bridge.runtime_manager import CodexRuntimeManager, RuntimeState, TurnState
from p4_codex_bridge.registry import RunRegistry
from p4_codex_bridge.app_server_capabilities import AppServerCapabilitySet, CapabilityStatus, FEATURE_METHODS
from p4_codex_bridge.security import SecurityDecision, SecurityDecisionResult

FAKE_CAPABILITIES = AppServerCapabilitySet({key: CapabilityStatus.SUPPORTED for key in FEATURE_METHODS}, "fake-schema", "v2")


FAKE_SERVER = r'''
import json,sys
thread="t-runtime"
thread_count=0
for line in sys.stdin:
 m=json.loads(line); method=m.get("method"); i=m.get("id")
 if method=="initialize":
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"protocolVersion":"v2","serverInfo":{"name":"fake"}}}),flush=True)
 elif method=="thread/start":
  thread_count+=1
  tid=thread if thread_count==1 else thread+"-"+str(thread_count)
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"thread":{"id":tid,"cwd":__import__('os').getcwd(),"model":"fake-model"}}}),flush=True)
 elif method=="thread/resume":
  tid=m["params"]["threadId"]
  if not tid.startswith(thread): print(json.dumps({"jsonrpc":"2.0","id":i,"error":{"code":-32000,"message":"thread unavailable"}}),flush=True)
  else: print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"thread":{"id":tid,"cwd":__import__('os').getcwd(),"model":"fake-model"}}}),flush=True)
 elif method=="thread/fork":
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"thread":{"id":"t-fork","cwd":__import__('os').getcwd(),"model":"fake-model","forkedFromId":thread}}}),flush=True)
 elif method=="thread/turns/list":
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"data":[{"id":"turn-1","status":"completed","items":[]} ]}}),flush=True)
 elif method=="turn/start":
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"turn":{"id":"turn-1"}}}),flush=True)
  p={"threadId":m["params"]["threadId"],"turnId":"turn-1"}
  print(json.dumps({"jsonrpc":"2.0","method":"turn/started","params":p}),flush=True)
  prompt=m.get("params",{}).get("input",[{}])[0].get("text","")
  if prompt=="APPROVAL":
   print(json.dumps({"jsonrpc":"2.0","id":91,"method":"item/commandExecution/requestApproval","params":{"threadId":m["params"]["threadId"],"turnId":"turn-1","itemId":"item-1","command":"echo safe","cwd":__import__('os').getcwd(),"reason":"test"}}),flush=True)
   decision=json.loads(sys.stdin.readline())
   if decision.get("id")!=91: sys.exit(4)
  if prompt=="HOLD": continue
  print(json.dumps({"jsonrpc":"2.0","method":"item/started","params":{**p,"item":{"id":"user-item","type":"userMessage"}}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"item/completed","params":{**p,"item":{"id":"user-item","type":"userMessage"}}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"item/started","params":{**p,"item":{"id":"agent-item","type":"agentMessage"}}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"item/agentMessage/delta","params":{**p,"delta":"OK"}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"item/completed","params":{**p,"item":{"id":"agent-item","type":"agentMessage","text":"OK"}}}),flush=True)
  print(json.dumps({"jsonrpc":"2.0","method":"turn/completed","params":{**p,"turn":{"status":"completed"}}}),flush=True)
 elif method=="turn/steer":
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{"turnId":m["params"]["expectedTurnId"]}}),flush=True)
  p={"threadId":m["params"]["threadId"],"turnId":"turn-1"}
  print(json.dumps({"jsonrpc":"2.0","method":"turn/completed","params":{**p,"turn":{"status":"completed"}}}),flush=True)
 elif method=="turn/interrupt":
  print(json.dumps({"jsonrpc":"2.0","id":i,"result":{}}),flush=True)
 elif method=="initialized": pass
'''


class RuntimeManagerTests(unittest.TestCase):
    def setUp(self):
        self.capability_discovery = patch("p4_codex_bridge.runtime_manager.discover_app_server_capabilities", return_value=FAKE_CAPABILITIES)
        self.capability_discovery.start()
        self.security_validation = patch("p4_codex_bridge.runtime_manager.validate_run_security",
            return_value=SecurityDecisionResult(SecurityDecision.ALLOW, policy_id="offline-fake"))
        self.security_validation.start()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = CodexRuntimeManager(cwd=self.root, database_path=self.root / "bridge.sqlite",
            lock_path=self.root / "runtime.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER])

    def tearDown(self):
        self.manager.stop(mode="FORCE")
        self.capability_discovery.stop()
        self.security_validation.stop()
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
        self.assertIn("AgentMessageDelta", observed_types)
        self.assertNotIn("AgentMessageDelta", event_types)
        self.assertIn("TurnCompleted", event_types)
        self.assertEqual(event_types.count("RESOURCE_RELEASED"), 1)
        inspected = registry.inspect(turn.bridge_run_id)
        self.assertEqual(inspected["server_id"], self.manager.instance_id)
        self.assertEqual(inspected["agent_role"], "validation")
        self.assertTrue(inspected["process_identity"])

    def test_resume_fork_and_steer_use_app_server_protocol(self):
        self.manager.start()
        parent = self.manager.create_thread()
        with self.assertRaises(KeyError): self.manager.fork_thread("missing-thread")
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            self.manager.fork_thread(parent.thread_id, last_turn_id="t1", before_turn_id="t2")
        with self.assertRaises(KeyError): self.manager.resume_thread("missing-thread")
        resumed = self.manager.resume_thread(parent.thread_id)
        self.assertTrue(resumed.remote_state_verified)
        child = self.manager.fork_thread(parent.thread_id, last_turn_id="turn-old", model="fork-model")
        self.assertEqual(child.parent_thread_id, parent.thread_id)
        self.assertEqual(child.model, "fork-model")
        turn = self.manager.start_turn(parent.thread_id, "HOLD")
        self.assertEqual(self.manager.steer_turn(parent.thread_id, turn.turn_id, "continue"), turn.turn_id)
        import time
        deadline = time.monotonic() + 2
        while turn.status != TurnState.COMPLETED and time.monotonic() < deadline: time.sleep(.01)
        self.assertEqual(turn.status, TurnState.COMPLETED)
        self.assertFalse(child.replay_complete)

    def test_recovered_thread_requires_explicit_resume(self):
        self.manager.start()
        thread = self.manager.create_thread()
        thread_id = thread.thread_id
        self.manager.stop(mode="WAIT")
        second = CodexRuntimeManager(cwd=self.root, database_path=self.root / "bridge.sqlite",
            lock_path=self.root / "runtime.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER])
        try:
            second.start()
            recovered = second.threads[thread_id]
            self.assertTrue(recovered.recovered)
            self.assertFalse(recovered.remote_state_verified)
            with self.assertRaisesRegex(RuntimeError, "explicitly resumed"):
                second.start_turn(thread_id, "not yet")
            second.resume_thread(thread_id)
            self.assertTrue(recovered.remote_state_verified)
            next_turn = second.start_turn(thread_id, "Reply OK")
            import time
            deadline = time.monotonic() + 2
            while next_turn.status != TurnState.COMPLETED and time.monotonic() < deadline: time.sleep(.01)
            self.assertEqual(next_turn.status, TurnState.COMPLETED)
        finally:
            second.stop(mode="FORCE")

    def test_same_manager_restart_invalidates_remote_thread_verification(self):
        self.manager.start(); thread = self.manager.create_thread()
        self.assertTrue(thread.remote_state_verified)
        self.manager.restart()
        self.assertTrue(thread.recovered)
        self.assertFalse(thread.remote_state_verified)
        with self.assertRaisesRegex(RuntimeError, "explicitly resumed"):
            self.manager.start_turn(thread.thread_id, "must resume")
        self.manager.resume_thread(thread.thread_id)
        self.assertTrue(thread.remote_state_verified)

    def test_runtime_approval_is_persisted_and_manually_resolved(self):
        self.manager.start()
        thread = self.manager.create_thread(approval_policy="on-request")
        turn = self.manager.start_turn(thread.thread_id, "APPROVAL")
        import time
        deadline = time.monotonic() + 2
        approvals = []
        while (turn.status != TurnState.WAITING_APPROVAL or not approvals) and time.monotonic() < deadline:
            approvals = self.manager.list_pending_approvals()
            if turn.status != TurnState.WAITING_APPROVAL or not approvals: time.sleep(.01)
        self.assertEqual(turn.status, TurnState.WAITING_APPROVAL)
        self.assertEqual(len(approvals), 1)
        approval = approvals[0]
        self.assertEqual(approval["bridge_run_id"], turn.bridge_run_id)
        self.assertEqual(approval["server_id"], self.manager.instance_id)
        from p4_codex_bridge import CodexBridge
        bridge = CodexBridge.__new__(CodexBridge)
        bridge.registry = RunRegistry(self.root / "bridge.sqlite")
        self.assertEqual(len(bridge.list_pending_approvals()), 1)
        watched = list(bridge.watch(turn.bridge_run_id))
        self.assertIn("ApprovalRequested", [event.get("type") for event in watched])
        bridge.approve(approval["approval_id"])
        with self.assertRaises(RuntimeError): self.manager.approve(approval["approval_id"])
        deadline = time.monotonic() + 2
        while turn.status not in {TurnState.COMPLETED, TurnState.FAILED} and time.monotonic() < deadline: time.sleep(.01)
        self.assertEqual(turn.status, TurnState.COMPLETED)
        self.assertEqual(self.manager.get_approval(approval["approval_id"])["status"], "RESOLVED")

    def test_approval_event_is_journaled_before_waiting_state_is_published(self):
        self.manager.start()
        thread = self.manager.create_thread(approval_policy="on-request")
        observed_statuses = []
        persist = self.manager._persist_runtime_event
        def record_order(kind, thread_id, turn_id, data):
            if kind == "ApprovalRequested":
                observed_statuses.append(self.manager.get_turn(turn_id).status)
            return persist(kind, thread_id, turn_id, data)
        self.manager._persist_runtime_event = record_order
        turn = self.manager.start_turn(thread.thread_id, "APPROVAL")
        import time
        deadline = time.monotonic() + 2
        while turn.status != TurnState.WAITING_APPROVAL and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(turn.status, TurnState.WAITING_APPROVAL)
        self.assertEqual(observed_statuses, [TurnState.RUNNING])
        from p4_codex_bridge import CodexBridge
        bridge = CodexBridge.__new__(CodexBridge)
        bridge.registry = RunRegistry(self.root / "bridge.sqlite")
        self.assertIn("ApprovalRequested", [event.get("type") for event in bridge.watch(turn.bridge_run_id)])

    def test_runtime_approval_timeout_rejects(self):
        manager = CodexRuntimeManager(cwd=self.root, database_path=self.root / "timeout.sqlite",
            lock_path=self.root / "timeout.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER], approval_timeout_seconds=.15)
        try:
            manager.start(); thread = manager.create_thread(approval_policy="on-request")
            turn = manager.start_turn(thread.thread_id, "APPROVAL")
            import time
            deadline = time.monotonic() + 2
            while turn.status not in {TurnState.COMPLETED, TurnState.FAILED} and time.monotonic() < deadline: time.sleep(.01)
            self.assertEqual(turn.status, TurnState.COMPLETED)
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(self.root / "timeout.sqlite")) as db:
                status, decision = db.execute("SELECT status,decision FROM runtime_approvals").fetchone()
            self.assertEqual((status, decision), ("RESOLVED", "decline"))
        finally: manager.stop(mode="FORCE")

    def test_pending_runtime_approval_becomes_stale_after_manager_restart(self):
        self.manager.start(); thread = self.manager.create_thread(approval_policy="on-request")
        self.manager.start_turn(thread.thread_id, "APPROVAL")
        import time
        deadline = time.monotonic() + 2
        while not self.manager.list_pending_approvals() and time.monotonic() < deadline: time.sleep(.01)
        approval_id = self.manager.list_pending_approvals()[0]["approval_id"]
        self.manager.stop(mode="FORCE")
        second = CodexRuntimeManager(cwd=self.root, database_path=self.root / "bridge.sqlite",
            lock_path=self.root / "runtime.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER])
        try:
            second.start()
            self.assertEqual(second.get_approval(approval_id)["status"], "STALE_LOCAL")
            self.assertEqual(second.list_pending_approvals(), [])
            with self.assertRaisesRegex(RuntimeError, "not owned"):
                second.approve(approval_id)
        finally: second.stop(mode="FORCE")

    def test_multiple_persisted_threads_resume_after_manager_restart(self):
        self.manager.start()
        first = self.manager.create_thread(); second_thread = self.manager.create_thread()
        self.manager.stop(mode="WAIT")
        manager = CodexRuntimeManager(cwd=self.root, database_path=self.root / "bridge.sqlite",
            lock_path=self.root / "runtime.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER])
        try:
            manager.start()
            self.assertEqual(len(manager.threads), 2)
            for thread_id in (first.thread_id, second_thread.thread_id):
                self.assertTrue(manager.threads[thread_id].recovered)
                manager.resume_thread(thread_id)
                self.assertTrue(manager.threads[thread_id].remote_state_verified)
        finally: manager.stop(mode="FORCE")

    def test_remote_terminal_turn_is_reconciled_without_reexecution(self):
        self.manager.start(); thread = self.manager.create_thread()
        turn = self.manager.start_turn(thread.thread_id, "HOLD")
        import time
        deadline = time.monotonic() + 2
        while turn.status != TurnState.RUNNING and time.monotonic() < deadline: time.sleep(.01)
        self.assertEqual(turn.status, TurnState.RUNNING)
        self.manager.stop(mode="FORCE")
        manager = CodexRuntimeManager(cwd=self.root, database_path=self.root / "bridge.sqlite",
            lock_path=self.root / "runtime.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER])
        try:
            manager.start()
            self.assertEqual(manager.turns[turn.turn_id].status, TurnState.UNKNOWN)
            from p4_codex_bridge import CodexBridge
            from p4_codex_bridge.registry import RunRegistry
            bridge = CodexBridge.__new__(CodexBridge)
            bridge.registry = RunRegistry(self.root / "bridge.sqlite")
            watched = list(bridge.watch(turn.bridge_run_id))
            self.assertIn("ReplayWarning", [event.get("type") for event in watched])
            snapshot = bridge.inspect(turn.bridge_run_id)
            self.assertTrue(snapshot["recovered"])
            self.assertFalse(snapshot["remote_state_verified"])
            self.assertFalse(snapshot["event_replay_complete"])
            recovered_thread = manager.resume_thread(thread.thread_id)
            self.assertEqual(recovered_thread.recovered_turns[turn.turn_id], "completed")
            self.assertEqual(manager.turns[turn.turn_id].status, TurnState.COMPLETED)
            self.assertEqual(manager.scheduler.get(turn.bridge_run_id)["status"], "COMPLETED")
            snapshot = bridge.inspect(turn.bridge_run_id)
            self.assertTrue(snapshot["remote_state_verified"])
        finally: manager.stop(mode="FORCE")

    def test_lifecycle_events_without_turn_id_are_attached_to_active_turn(self):
        server = FAKE_SERVER.replace('p={"threadId":m["params"]["threadId"],"turnId":"turn-1"}', 'p={"threadId":m["params"]["threadId"]}')
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
            self.assertIn("AgentMessageDelta", [event["type"] for event in turn.events])
            self.assertNotIn("AgentMessageDelta", types)
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

    def test_version_one_runtime_schema_migrates_additively_to_two(self):
        import sqlite3
        from contextlib import closing
        path = self.root / "v1.sqlite"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE bridge_schema(version INTEGER NOT NULL)")
            db.execute("INSERT INTO bridge_schema VALUES(1)")
            db.execute("CREATE TABLE runtime_servers(instance_id TEXT PRIMARY KEY,pid INTEGER,command_fingerprint TEXT NOT NULL,started_at TEXT NOT NULL,status TEXT NOT NULL,last_error TEXT)")
            db.execute("CREATE TABLE runtime_threads(thread_id TEXT PRIMARY KEY,cwd TEXT NOT NULL,profile TEXT NOT NULL,model TEXT,permissions_json TEXT NOT NULL,config_policy TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,agent_metadata_json TEXT NOT NULL DEFAULT '{}',server_id TEXT)")
            db.execute("CREATE TABLE runtime_turns(turn_id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,model TEXT,error TEXT,final_text TEXT NOT NULL DEFAULT '',bridge_run_id TEXT,agent_metadata_json TEXT NOT NULL DEFAULT '{}')")
            db.execute("CREATE TABLE runtime_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,thread_id TEXT,turn_id TEXT,event_type TEXT NOT NULL,created_at TEXT NOT NULL,payload_json TEXT NOT NULL)")
        manager = CodexRuntimeManager(cwd=self.root, database_path=path, command=[sys.executable, "-c", "pass"])
        with closing(sqlite3.connect(path)) as db:
            version = db.execute("SELECT version FROM bridge_schema").fetchone()[0]
            columns = {row[1] for row in db.execute("PRAGMA table_info(runtime_threads)")}
        self.assertEqual(version, 2)
        self.assertTrue({"parent_thread_id", "resumable", "remote_state_verified", "ephemeral"}.issubset(columns))

    def test_interrupted_schema_migration_rolls_back_and_retries(self):
        import sqlite3
        from contextlib import closing
        path = self.root / "interrupted.sqlite"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE bridge_schema(version INTEGER NOT NULL)")
            db.execute("INSERT INTO bridge_schema VALUES(1)")
            db.execute("CREATE TABLE runtime_threads(thread_id TEXT PRIMARY KEY,cwd TEXT NOT NULL,profile TEXT NOT NULL,model TEXT,permissions_json TEXT NOT NULL,config_policy TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL)")
            db.execute("CREATE TABLE runtime_turns(turn_id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,model TEXT,error TEXT,final_text TEXT NOT NULL DEFAULT '')")
        real_connect = sqlite3.connect
        def connect_with_migration_fault(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connection.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_ALTER_TABLE else sqlite3.SQLITE_OK)
            return connection
        with patch("sqlite3.connect", side_effect=connect_with_migration_fault):
            with self.assertRaises(sqlite3.DatabaseError):
                CodexRuntimeManager._schema(path)
        with closing(real_connect(path)) as db:
            self.assertEqual(db.execute("SELECT version FROM bridge_schema").fetchone()[0], 1)
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("runtime_control_requests", tables)
            self.assertNotIn("turn_events", tables)
        CodexRuntimeManager._schema(path)
        with closing(real_connect(path)) as db:
            self.assertEqual(db.execute("SELECT version FROM bridge_schema").fetchone()[0], 2)
            columns = {row[1] for row in db.execute("PRAGMA table_info(runtime_threads)")}
        self.assertTrue({"parent_thread_id", "resumable", "remote_state_verified", "ephemeral"}.issubset(columns))

    def test_locked_database_migration_fails_with_bounded_timeout_then_recovers(self):
        import sqlite3
        from contextlib import closing
        path = self.root / "locked.sqlite"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE sentinel(value TEXT)")
        blocker = sqlite3.connect(path)
        blocker.execute("BEGIN EXCLUSIVE")
        started = __import__("time").monotonic()
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                CodexRuntimeManager._schema(path)
            self.assertLess(__import__("time").monotonic() - started, 3.5)
        finally:
            blocker.rollback()
            blocker.close()
        CodexRuntimeManager._schema(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT version FROM bridge_schema").fetchone()[0], 2)

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

    def test_approval_runtime_sqlite_teardown_joins_workers_before_immediate_delete(self):
        import shutil
        import time
        for index in range(6):
            state = self.root / f"approval-teardown-{index}"
            state.mkdir()
            manager = CodexRuntimeManager(cwd=self.root, database_path=state / "bridge.sqlite",
                lock_path=state / "runtime.lock", command=[sys.executable, "-u", "-c", FAKE_SERVER])
            try:
                manager.start()
                thread = manager.create_thread(approval_policy="on-request")
                turn = manager.start_turn(thread.thread_id, "APPROVAL", access_mode="WRITE")
                deadline = time.monotonic() + 2
                approvals = []
                while not approvals and time.monotonic() < deadline:
                    approvals = manager.list_pending_approvals()
                    if not approvals: time.sleep(.01)
                self.assertEqual(turn.status, TurnState.WAITING_APPROVAL)
                self.assertEqual(len(approvals), 1)
                manager.reject(approvals[0]["approval_id"])
                deadline = time.monotonic() + 2
                while turn.status not in {TurnState.COMPLETED, TurnState.FAILED} and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(turn.status, TurnState.COMPLETED)
            finally:
                manager.stop(mode="WAIT")
            self.assertFalse(manager._control_thread.is_alive())
            self.assertFalse(manager._reader.is_alive())
            self.assertFalse(any(worker.is_alive() for worker in manager._background_threads))
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
