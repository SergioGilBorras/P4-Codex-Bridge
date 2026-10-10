from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from portable_tempdirs import TemporaryDirectoryError, temporary_directory

from p4_codex_bridge import _worker
from p4_codex_bridge.client import CodexBridge
from p4_codex_bridge.registry import RunRegistry


class _WorkerRegistry:
    def __init__(self, result_path: Path, database_path: Path) -> None:
        self.result_path = result_path
        self.path = database_path
        self.updates: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.state: dict[str, object] = {}
        self.events: list[tuple[str, dict[str, object]]] = []

    def raw(self, _run_id: str) -> dict[str, str]:
        return {"result_path": str(self.result_path)}

    def update(self, *args: object, **kwargs: object) -> None:
        self.updates.append((args, kwargs))
        self.state.update(kwargs)

    def add_run_event(self, _run_id: str, event_type: str, data: dict[str, object]) -> None:
        self.events.append((event_type, data))


class PortableTemporaryDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._test_temp_owner = temporary_directory("P4BridgeRegression")
        self.root = Path(self._test_temp_owner.name)

    def tearDown(self) -> None:
        self._test_temp_owner.cleanup()

    def test_explicit_parent_creation_and_identity_checked_cleanup(self) -> None:
        parent = self.root / "authorized-parent"
        parent.mkdir()
        with temporary_directory("P4BridgeTest", parent=parent) as raw_path:
            managed = Path(raw_path)
            self.assertEqual(managed.parent, parent.resolve())
            marker = managed / "marker.txt"
            marker.write_text("temporary", encoding="utf-8")
            self.assertEqual(marker.read_text(encoding="utf-8"), "temporary")
        self.assertFalse(managed.exists())
        self.assertEqual(list(parent.iterdir()), [])

    def test_unavailable_explicit_parent_fails_without_fallback(self) -> None:
        missing_parent = self.root / "not-created"
        with self.assertRaises((TemporaryDirectoryError, OSError)):
            temporary_directory("P4BridgeTest", parent=missing_parent)
        self.assertFalse(missing_parent.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_second_worker_file_allocation_failure_cleans_first_file_and_preserves_state(self) -> None:
        state_dir = self.root / "state"
        state_temp = state_dir / "temp"
        state_temp.mkdir(parents=True)
        result_path = self.root / "result.json"
        database_path = state_dir / "runs.sqlite3"
        database_path.write_bytes(b"persistent-state-sentinel")
        registry = _WorkerRegistry(result_path, database_path)
        original_open = Path.open

        def fail_last_message(path: Path, *args: object, **kwargs: object):
            if path.name == "last-message.txt":
                raise PermissionError("injected second temporary file allocation failure")
            return original_open(path, *args, **kwargs)

        request = {
            "state_dir": str(state_dir),
            "output_schema": {"type": "object"},
            "capture_last_message": True,
        }
        with patch.object(Path, "open", fail_last_message):
            _worker.execute(registry, "br_temp_failure", request)

        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["error"]["code"], "TEMPORARY_FILE_PREPARATION_FAILED")
        self.assertEqual(list(state_temp.iterdir()), [])
        self.assertEqual(database_path.read_bytes(), b"persistent-state-sentinel")
        self.assertEqual(registry.updates[-1][1]["status"], "FAILED")

    def test_unexpected_worker_exception_cleans_managed_directory_and_preserves_cause(self) -> None:
        state_dir = self.root / "state"
        (state_dir / "temp").mkdir(parents=True)
        registry = _WorkerRegistry(self.root / "result.json", state_dir / "runs.sqlite3")
        request = {"state_dir": str(state_dir), "capture_last_message": True}
        with patch.object(_worker, "_execute_with_temp_directory", side_effect=RuntimeError("sentinel failure")):
            with self.assertRaisesRegex(RuntimeError, "sentinel failure"):
                _worker.execute(registry, "br_temp_exception", request)
        self.assertEqual(list((state_dir / "temp").iterdir()), [])

    def test_temp_directory_permission_denial_is_controlled_and_has_no_fallback(self) -> None:
        state_dir = self.root / "state"
        (state_dir / "temp").mkdir(parents=True)
        registry = _WorkerRegistry(self.root / "result.json", state_dir / "runs.sqlite3")
        request = {"state_dir": str(state_dir), "capture_last_message": True}
        with patch("p4_codex_bridge._worker.temporary_directory", side_effect=PermissionError("injected")):
            _worker.execute(registry, "br_temp_denied", request)
        result = json.loads(registry.result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["error"]["code"], "TEMPORARY_STORAGE_UNAVAILABLE")
        self.assertEqual(list((state_dir / "temp").iterdir()), [])
        self.assertFalse((self.root / "P4CodexWorker").exists())

    def test_cleanup_failure_is_logged_separately_without_replacing_primary_error(self) -> None:
        state_dir = self.root / "state"
        parent = state_dir / "temp"
        parent.mkdir(parents=True)
        owner = temporary_directory("P4BridgeTest", parent=parent)
        registry = _WorkerRegistry(self.root / "result.json", state_dir / "runs.sqlite3")
        request = {"state_dir": str(state_dir), "capture_last_message": True}
        try:
            with patch("p4_codex_bridge._worker.temporary_directory", return_value=owner), \
                    patch.object(owner, "cleanup", side_effect=PermissionError("injected cleanup denial")), \
                    patch.object(_worker, "_execute_with_temp_directory", side_effect=RuntimeError("primary failure")), \
                    self.assertLogs("p4_codex_bridge.worker", level="ERROR") as logs:
                with self.assertRaisesRegex(RuntimeError, "primary failure"):
                    _worker.execute(registry, "br_cleanup_failure", request)
            self.assertTrue(any("managed temporary cleanup failed" in line for line in logs.output))
            self.assertTrue(any(event == "TemporaryCleanupDeferred" for event, _ in registry.events))
        finally:
            owner.cleanup()

    def test_cleanup_failure_after_result_preserves_completion_and_session_id(self) -> None:
        for ephemeral in (True, False):
            with self.subTest(ephemeral=ephemeral):
                state_dir = self.root / f"state-{ephemeral}"
                parent = state_dir / "temp"
                parent.mkdir(parents=True)
                result_path = self.root / f"result-{ephemeral}.json"
                registry = RunRegistry(state_dir / "runs.sqlite3")
                run_id = f"br_cleanup_completed_{ephemeral}"
                registry.create(
                    run_id, backend="exec", cwd=str(self.root), model=None,
                    profile="analysis", result_path=str(result_path),
                )
                owner = temporary_directory("P4BridgeTest", parent=parent)
                session_id = "persisted-session-123"

                def complete_run(*args: object) -> None:
                    run_registry = args[0]
                    run_id = args[1]
                    result = {
                        "ok": True,
                        "bridge_run_id": run_id,
                        "exit_code": 0,
                        "content": "OK",
                        "stderr": "",
                        "structured_output": None,
                        "session_id": session_id,
                        "raw_output": None,
                        "error": None,
                        "duration_ms": 1,
                    }
                    result_path.write_text(json.dumps(result), encoding="utf-8")
                    run_registry.update(run_id, status="COMPLETED", exit_code=0, session_id=session_id)

                request = {
                    "state_dir": str(state_dir),
                    "capture_last_message": True,
                    "ephemeral": ephemeral,
                }
                try:
                    with patch("p4_codex_bridge._worker.temporary_directory", return_value=owner), \
                            patch.object(_worker, "_execute_with_temp_directory", side_effect=complete_run), \
                            patch.object(owner, "cleanup", side_effect=PermissionError("private cleanup detail")), \
                            self.assertLogs("p4_codex_bridge.worker", level="WARNING") as logs:
                        _worker.execute(registry, run_id, request)

                    persisted = json.loads(result_path.read_text(encoding="utf-8"))
                    self.assertTrue(persisted["ok"])
                    self.assertEqual(persisted["session_id"], session_id)
                    bridge = CodexBridge.__new__(CodexBridge)
                    bridge.registry = registry
                    result = bridge.read_result(run_id)
                    self.assertIsNotNone(result)
                    self.assertTrue(result.ok)
                    self.assertEqual(result.session_id, session_id)
                    inspected = bridge.inspect(run_id)
                    self.assertEqual(inspected["status"], "COMPLETED")
                    self.assertEqual(inspected["session_id"], session_id)
                    events = registry.events_for(registry.raw(run_id))
                    deferred = [event for event in events if event.get("type") == "TemporaryCleanupDeferred"]
                    self.assertEqual(len(deferred), 1)
                    log_text = "\n".join(logs.output)
                    self.assertNotIn("private cleanup detail", log_text)
                    self.assertNotIn(str(self.root), log_text)
                finally:
                    owner.cleanup()


if __name__ == "__main__":
    unittest.main()
