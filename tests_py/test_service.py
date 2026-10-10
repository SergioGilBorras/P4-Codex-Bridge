from __future__ import annotations

import os
import subprocess
import sys
from tests_py._portable_temp import TemporaryDirectory
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from p4_codex_bridge.service import (ServiceConfig, request_service_action, service_status, validate_config,
                                     maintenance_report, database_health, _ensure_service_schema,
                                     _persist_capability_snapshot, doctor_report)
from p4_codex_bridge.runtime import resolve_codex_command


class ServiceConfigTests(unittest.TestCase):
    def test_codex_executable_environment_name_is_prefixed_and_legacy_alias_is_ignored(self):
        with TemporaryDirectory() as temp:
            fake = Path(temp) / "codex.py"
            fake.write_text("pass\n", encoding="utf-8")
            with patch.dict(os.environ, {"PATH": "", "P4_CODEX_BRIDGE_CODEX_EXECUTABLE": str(fake)}, clear=True):
                self.assertEqual(resolve_codex_command(), [sys.executable, str(fake.resolve())])
            with patch.dict(os.environ, {"PATH": "", "CODEX_BIN": str(fake)}, clear=True):
                with self.assertRaises(FileNotFoundError):
                    resolve_codex_command()

    def test_defaults_and_precedence_cli_state_over_environment_over_file(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cwd = root / "workspace"
            cwd.mkdir()
            cfg_file = root / "p4-codex.toml"
            cfg_file.write_text(f'[service]\ncwd = "{cwd.as_posix()}"\nstate_dir = "{(root / "file-state").as_posix()}"\n', encoding="utf-8")
            with patch.dict(os.environ, {"P4_CODEX_BRIDGE_STATE_DIR": str(root / "env-state")}):
                effective = ServiceConfig.load(cfg_file, state_dir=root / "cli-state")
                self.assertEqual(effective.state_dir, (root / "cli-state").resolve())
                from_env = ServiceConfig.load(cfg_file)
                self.assertEqual(from_env.state_dir, (root / "env-state").resolve())
            with patch.dict(os.environ, {}, clear=True):
                from_file = ServiceConfig.load(cfg_file)
                self.assertEqual(from_file.state_dir, (root / "file-state").resolve())

    def test_config_validation_rejects_unknown_keys_and_limits(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cwd = root / "workspace"
            cwd.mkdir()
            config = root / "bad.toml"
            config.write_text(f'[service]\ncwd = "{cwd.as_posix()}"\nunknown = true\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown keys"):
                validate_config(config, state_dir=root / "isolated-state")
            config.write_text(f'[service]\ncwd = "{cwd.as_posix()}"\nshutdown_policy = "AUTO"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "shutdown_policy"):
                validate_config(config, state_dir=root / "isolated-state")
            config.write_text(f'config_version = 1\n[service]\ncwd = "{cwd.as_posix()}"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown top-level section"):
                validate_config(config, state_dir=root / "isolated-state")

    def test_state_dir_with_spaces_and_config_show_are_supported(self):
        with TemporaryDirectory(prefix="P4 Bridge State ") as temp:
            root = Path(temp)
            cwd = root / "Program Files workspace"
            cwd.mkdir()
            config = root / "service.toml"
            config.write_text(f'[service]\ncwd = "{cwd.as_posix()}"\n', encoding="utf-8")
            report = validate_config(config, state_dir=root / "state with spaces")
            self.assertTrue(report["valid"])
            self.assertTrue(str(report["config"]["state_dir"]).endswith("state with spaces"))

    def test_retention_config_is_typed_and_bounded(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cwd = root / "workspace"
            cwd.mkdir()
            config = root / "p4-codex.toml"
            config.write_text(f'[service]\ncwd = "{cwd.as_posix()}"\n[retention]\ndays = 10\nmax_completed_runs = 12\nmax_events_per_run = 50\n', encoding="utf-8")
            loaded = ServiceConfig.load(config, state_dir=root / "isolated-state")
            self.assertEqual((loaded.retention_days, loaded.max_completed_runs, loaded.max_events_per_run), (10, 12, 50))

    def test_config_accepts_utf8_bom_written_by_windows_tools(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cwd = root / "workspace"
            cwd.mkdir()
            config = root / "bom.toml"
            config.write_bytes(b'\xef\xbb\xbf[service]\ncwd = "' + cwd.as_posix().encode() + b'"\n')
            self.assertEqual(ServiceConfig.load(config, state_dir=root / "isolated-state").cwd, cwd.resolve())

    def test_doctor_uses_fake_cli_and_does_not_create_state_files(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cwd = root / "workspace"
            cwd.mkdir()
            state = root / "not-created"
            fake = root / "fake_codex.py"
            fake.write_text("import sys\na=sys.argv[1:]\nif a==['--version']: print('codex-cli fake-0.160.1')\nelif a==['login','status']: print('logged in'); sys.exit(0)\nelif a in (['app-server','--help'],['exec','--help']): print('Usage: codex'); sys.exit(0)\n", encoding="utf-8")
            config = ServiceConfig(state_dir=state, cwd=cwd, log_dir=root / "logs", codex_executable=str(fake))
            with patch.dict(os.environ, {"P4_CODEX_BRIDGE_CODEX_EXECUTABLE": str(fake)}):
                report = doctor_report(config)
            self.assertTrue(report["ok"], report)
            self.assertFalse(state.exists())
            self.assertEqual(report["entrypoints"]["module_entrypoint"]["status"], "PASS")
            self.assertIn(report["entrypoints"]["cmd_launcher"]["status"], {"PASS", "NOT_INSTALLED"})
            self.assertIn(report["entrypoints"]["console_script_exe"]["status"],
                          {"UNKNOWN", "NOT_INSTALLED"})


class MaintenanceTests(unittest.TestCase):
    def test_corrupt_database_health_is_read_only_and_reports_recovery_action(self):
        with TemporaryDirectory() as temp:
            state = Path(temp)
            db_path = state / "runs.sqlite3"
            corrupt = b"this is not a sqlite database\x00\xff"
            db_path.write_bytes(corrupt)
            report = database_health(state)
            self.assertFalse(report["available"])
            self.assertEqual(report["integrity"], "ERROR")
            self.assertEqual(report["migration_status"], "DatabaseError")
            self.assertEqual(db_path.read_bytes(), corrupt)

    def test_cleanup_dry_run_and_clean_preserve_active_lost_and_pending_approval(self):
        import sqlite3
        from datetime import datetime, timedelta, timezone
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cwd = root / "workspace"
            cwd.mkdir()
            state = root / "state"
            state.mkdir()
            db_path = state / "runs.sqlite3"
            old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
            future = datetime.now(timezone.utc).isoformat()
            db = sqlite3.connect(db_path)
            db.executescript("""
                CREATE TABLE scheduler_runs(bridge_run_id TEXT PRIMARY KEY,turn_id TEXT,status TEXT,submitted_at TEXT,finished_at TEXT);
                CREATE TABLE scheduler_payloads(bridge_run_id TEXT PRIMARY KEY,payload_json TEXT);
                CREATE TABLE runs(bridge_run_id TEXT PRIMARY KEY,turn_id TEXT,status TEXT,started_at TEXT,result_path TEXT);
                CREATE TABLE turn_events(sequence INTEGER PRIMARY KEY,bridge_run_id TEXT,turn_id TEXT);
                CREATE TABLE runtime_events(sequence INTEGER PRIMARY KEY,turn_id TEXT);
                CREATE TABLE runtime_approvals(approval_id TEXT PRIMARY KEY,bridge_run_id TEXT,status TEXT,turn_id TEXT);
                CREATE TABLE bridge_service_commands(request_id TEXT PRIMARY KEY,action TEXT,status TEXT,created_at TEXT);
                CREATE TABLE runtime_servers(instance_id TEXT PRIMARY KEY,status TEXT,started_at TEXT);
            """)
            db.executemany("INSERT INTO scheduler_runs VALUES(?,?,?,?,?)", [
                ("br_old", "tr_old", "COMPLETED", old, old),
                ("br_active", "tr_active", "RUNNING", old, None),
                ("br_lost", "tr_lost", "LOST", old, old),
            ])
            db.executemany("INSERT INTO scheduler_payloads VALUES(?,?)", [("br_old", "{}"), ("br_active", "{}")])
            db.execute("INSERT INTO runtime_approvals VALUES('ap_pending','br_old','PENDING','tr_old')")
            db.commit()
            db.close()
            config = ServiceConfig(state_dir=state, cwd=cwd, log_dir=state / "logs", retention_days=30)
            preview = maintenance_report(state, config, dry_run=True)
            self.assertEqual(preview["would_delete"]["scheduler_runs"], 1)
            self.assertEqual(preview["deleted"], {})
            self.assertTrue(database_health(state)["integrity"] == "ok")
            result = maintenance_report(state, config, dry_run=False)
            check = sqlite3.connect(db_path)
            statuses = dict(check.execute("SELECT bridge_run_id,status FROM scheduler_runs"))
            payloads = set(row[0] for row in check.execute("SELECT bridge_run_id FROM scheduler_payloads"))
            approvals = list(check.execute("SELECT status FROM runtime_approvals"))
            check.close()
            self.assertNotIn("br_old", statuses)
            self.assertEqual(statuses, {"br_active": "RUNNING", "br_lost": "LOST"})
            self.assertEqual(payloads, {"br_active"})
            self.assertEqual(approvals, [("PENDING",)])
            self.assertEqual(result["deleted"]["scheduler_runs"], 1)

    def test_capability_snapshot_compares_only_sanitized_small_records(self):
        from p4_codex_bridge import __version__
        with TemporaryDirectory() as temp:
            db_path = Path(temp) / "runs.sqlite3"
            _ensure_service_schema(db_path)
            first = _persist_capability_snapshot(db_path, "2026-10-07T00:00:00+00:00", "Codex 0.160.1",
                {"protocol_version": "v2", "bridge_version": __version__, "bridge_can_support": ["x"],
                 "codex_supports": {"methods": {"x": {"effective_available": True}}}, "secret": "must-not-persist"})
            second = _persist_capability_snapshot(db_path, "2026-10-07T00:01:00+00:00", "Codex 0.160.1",
                {"protocol_version": "v2", "bridge_version": __version__, "bridge_can_support": ["x"],
                 "codex_supports": {"methods": {"x": {"effective_available": True}}}})
            self.assertIsNone(first["previous"])
            self.assertEqual(second["changed"], False)
            self.assertNotIn("secret", repr(second))


class ResidentServiceTests(unittest.TestCase):
    def test_foreground_fake_service_status_metrics_stop_and_singleton(self):
        with TemporaryDirectory(prefix="p4 service state ") as temp:
            root = Path(temp)
            cwd = root / "workspace"
            cwd.mkdir()
            state = root / "state dir"
            config = root / "service.toml"
            config.write_text(f'[service]\ncwd = "{cwd.as_posix()}"\n', encoding="utf-8")
            command = [sys.executable, "-m", "p4_codex_bridge", "service", "run", "--fake",
                       "--config", str(config), "--state-dir", str(state)]
            env = dict(os.environ)
            package_root = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
            first = subprocess.Popen(command, cwd=package_root, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
            try:
                deadline = time.monotonic() + 12
                snapshot = service_status(state)
                while time.monotonic() < deadline and snapshot.get("state") != "HEALTHY":
                    if first.poll() is not None:
                        self.fail("fake foreground service exited before becoming healthy")
                    time.sleep(0.1)
                    snapshot = service_status(state)
                self.assertEqual(snapshot["state"], "HEALTHY")
                self.assertEqual(snapshot["codex_version"], "FAKE")
                self.assertEqual(snapshot["queue_length"], 0)
                self.assertTrue(snapshot["db_health"])
                self.assertEqual(len(snapshot["config_fingerprint"]), 64)
                self.assertIn("process_identity", snapshot)
                self.assertIn("process_identity_verified", snapshot)
                second = subprocess.run(command, cwd=package_root, env=env, capture_output=True, text=True,
                                        timeout=8, shell=False)
                self.assertNotEqual(second.returncode, 0)
                self.assertEqual(service_status(state)["instance_id"], snapshot["instance_id"])
                demo_call = subprocess.run([sys.executable, "-m", "p4_codex_bridge", "service", "demo", "--config", str(config),
                    "--state-dir", str(state), "--timeout", "8"], cwd=package_root, env=env,
                    capture_output=True, text=True, timeout=10, shell=False)
                self.assertEqual(demo_call.returncode, 0, demo_call.stderr)
                demo = __import__("json").loads(demo_call.stdout)
                self.assertEqual(demo["status"], "COMPLETED")
                run_ids = demo["result"]["run_ids"]
                self.assertEqual(len(run_ids), 3)
                rows = subprocess.run([sys.executable, "-m", "p4_codex_bridge", "ps", "--json", "--state-dir", str(state)],
                    cwd=package_root, env=env, capture_output=True, text=True, timeout=8, shell=False)
                self.assertEqual(rows.returncode, 0, rows.stderr)
                discovered = __import__("json").loads(rows.stdout)
                self.assertEqual(len([row for row in discovered if row["bridge_run_id"] in run_ids]), 3)
                health = subprocess.run([sys.executable, "-m", "p4_codex_bridge", "health", "--json", "--config", str(config), "--state-dir", str(state)],
                    cwd=package_root, env=env, capture_output=True, text=True, timeout=8, shell=False)
                self.assertEqual(health.returncode, 0, health.stderr)
                self.assertEqual(__import__("json").loads(health.stdout)["state"], "HEALTHY")
                metrics = subprocess.run([sys.executable, "-m", "p4_codex_bridge", "metrics", "--json", "--config", str(config), "--state-dir", str(state)],
                    cwd=package_root, env=env, capture_output=True, text=True, timeout=8, shell=False)
                self.assertEqual(metrics.returncode, 0, metrics.stderr)
                self.assertIn("queue_length", __import__("json").loads(metrics.stdout))
                resources = subprocess.run([sys.executable, "-m", "p4_codex_bridge", "resources", "--state-dir", str(state)],
                    cwd=package_root, env=env, capture_output=True, text=True, timeout=8, shell=False)
                self.assertEqual(resources.returncode, 0, resources.stderr)
                watched = subprocess.run([sys.executable, "-m", "p4_codex_bridge", "watch", run_ids[0], "--state-dir", str(state)],
                    cwd=package_root, env=env, capture_output=True, text=True, timeout=8, shell=False)
                self.assertEqual(watched.returncode, 0, watched.stderr)
                self.assertIn("SUBMITTED", watched.stdout)
                inspected = subprocess.run([sys.executable, "-m", "p4_codex_bridge", "inspect", run_ids[0], "--state-dir", str(state)],
                    cwd=package_root, env=env, capture_output=True, text=True, timeout=8, shell=False)
                self.assertEqual(inspected.returncode, 0, inspected.stderr)
                self.assertEqual(__import__("json").loads(inspected.stdout)["backend"], "app-server")
                stop_call = subprocess.run([sys.executable, "-m", "p4_codex_bridge", "service", "stop", "--config", str(config),
                    "--state-dir", str(state), "--timeout", "60"], cwd=package_root, env=env,
                    capture_output=True, text=True, timeout=70, shell=False)
                self.assertEqual(stop_call.returncode, 0, f"stdout={stop_call.stdout!r}; stderr={stop_call.stderr!r}")
                stopped = __import__("json").loads(stop_call.stdout)
                self.assertEqual(stopped["status"], "COMPLETED")
                self.assertEqual(first.wait(timeout=5), 0)
                self.assertEqual(service_status(state)["state"], "STOPPED")
            finally:
                if first.poll() is None:
                    request_service_action(state, "stop", timeout=10)
                    first.wait(timeout=15)
                if first.stdout:
                    first.stdout.close()
                if first.stderr:
                    first.stderr.close()


if __name__ == "__main__":
    unittest.main()
