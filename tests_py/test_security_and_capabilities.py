from __future__ import annotations

import json
import sys
import tempfile
from tests_py._portable_temp import TemporaryDirectory
import unittest
from pathlib import Path
from unittest.mock import patch

from portable_tempdirs import temporary_directory

from p4_codex_bridge.app_server_capabilities import (
    AppServerCapabilitySet, AppServerSchemaSnapshot, CapabilityStatus, FEATURE_METHODS,
    discover_app_server_capabilities, parse_schema_capabilities,
)
from p4_codex_bridge.compatibility import CapabilitySet, CodexVersionInfo, CompatibilityStatus, assess_compatibility
from p4_codex_bridge.errors import CapabilityIsolationUnavailableError, CapabilityUnavailableError, RunSecurityRejectedError
from p4_codex_bridge.client import CodexBridge
from p4_codex_bridge.runtime_manager import CodexRuntimeManager, RuntimeState
from p4_codex_bridge.security import ProjectTrust, RunSecurityPolicy, SecurityDecision, validate_run_security


class RunSecurityTests(unittest.TestCase):
    def test_direct_and_managed_exec_paths_fail_closed_before_launch(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            bridge = CodexBridge(state_dir=root / "state", allowed_roots=[root])
            with self.assertRaises(RunSecurityRejectedError):
                bridge.run("x", cwd=root)
            with self.assertRaises(RunSecurityRejectedError):
                bridge.start("x", cwd=root)

    def test_runtime_manager_path_fails_closed_before_rpc(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            caps = AppServerCapabilitySet({key: CapabilityStatus.SUPPORTED for key in FEATURE_METHODS}, "fixture")
            # Security rejection must happen before any RPC; the test must not
            # depend on a real Codex executable being installed on the runner.
            manager = CodexRuntimeManager(cwd=root, database_path=root / "runtime.sqlite3",
                                         capability_set=caps, command=["fake-codex"])
            manager.state = RuntimeState.HEALTHY
            with self.assertRaises(RunSecurityRejectedError):
                manager.create_thread(cwd=root)
            manager.stop(mode="FORCE")

    def test_default_unknown_app_server_rejected_and_no_false_isolation(self):
        with self.assertRaises(RunSecurityRejectedError):
            validate_run_security(None, backend="app-server", config_policy="project")
        with self.assertRaisesRegex(RunSecurityRejectedError, "effective_external_mcp_set_unknown"):
            validate_run_security(None, backend="exec", config_policy="isolated")
        with self.assertRaises(CapabilityIsolationUnavailableError):
            validate_run_security(RunSecurityPolicy(require_mcp_isolation=True), backend="exec", config_policy="isolated")

    def test_unknown_project_cannot_enable_context_without_trust(self):
        policy = RunSecurityPolicy(allow_project_config=True)
        with self.assertRaisesRegex(RunSecurityRejectedError, "trusted"):
            validate_run_security(policy, backend="exec", config_policy="project")

    def test_acknowledged_external_mcp_risk_is_explicit_and_warned(self):
        policy = RunSecurityPolicy(project_trust=ProjectTrust.TRUSTED, allow_external_mcps=True,
            allow_side_effect_mcps=True, explicit_risk_acknowledgement=True, policy_id="operator-opt-in")
        result = validate_run_security(policy, backend="app-server", config_policy="project")
        self.assertEqual(result.decision, SecurityDecision.ALLOW_WITH_WARNING)
        self.assertTrue(result.warnings)

    def test_workspace_context_files_are_detected_within_project_boundary(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "repo"; root.mkdir(); (root / ".git").mkdir()
            cwd = root / "nested"; cwd.mkdir()
            (root / "AGENTS.md").write_text("inert")
            with self.assertRaisesRegex(RunSecurityRejectedError, "agents_file_present"):
                validate_run_security(None, backend="exec", config_policy="isolated", cwd=cwd)


class AppServerPreflightTests(unittest.TestCase):
    def test_committed_schema_fixtures_cover_method_presence_rename_and_corruption(self):
        fixture_root = Path(__file__).parent / "fixtures" / "app_server_schema"
        current = parse_schema_capabilities([fixture_root / "method_properties.json"], codex_version="0.160.1")
        changed = parse_schema_capabilities([fixture_root / "renamed_methods.json"])
        corrupt = parse_schema_capabilities([fixture_root / "malformed.json"])
        self.assertEqual(current.status("app_server.thread.create"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(current.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(changed.status("app_server.thread.create"), CapabilityStatus.UNSUPPORTED)
        self.assertEqual(changed.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertTrue(all(status == CapabilityStatus.UNKNOWN for status in corrupt.statuses.values()))

    def test_committed_schema_fixtures_cover_method_presence_rename_and_corruption(self):
        fixture_root = Path(__file__).parent / "fixtures" / "app_server_schema"
        current = parse_schema_capabilities([fixture_root / "method_properties.json"], codex_version="0.160.1")
        changed = parse_schema_capabilities([fixture_root / "renamed_methods.json"])
        corrupt = parse_schema_capabilities([fixture_root / "malformed.json"])
        self.assertEqual(current.status("app_server.thread.create"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(current.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(changed.status("app_server.thread.create"), CapabilityStatus.UNSUPPORTED)
        self.assertEqual(changed.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertTrue(all(status == CapabilityStatus.UNKNOWN for status in corrupt.statuses.values()))

    def test_schema_methods_produce_machine_readable_statuses(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "schema.json"
            methods = ["thread/start", "turn/start", "turn/steer", "turn/interrupt", "thread/resume",
                       "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                       "item/permissions/requestApproval"]
            path.write_text(json.dumps({"methods": [{"method": value} for value in methods]}), encoding="utf-8")
            result = parse_schema_capabilities([path], protocol_version="v2")
        self.assertEqual(result.status("app_server.thread.create"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(result.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(result.status("app_server.thread.fork"), CapabilityStatus.UNSUPPORTED)
        self.assertEqual(result.status("app_server.approvals"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)

    def test_json_schema_method_const_and_enum_are_normalized_without_text_false_positives(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "generated.json"
            path.write_text(json.dumps({"properties": {
                "method": {"const": "thread/start", "description": "not-a-rpc/method"},
                "notification": {"properties": {"method": {"enum": ["turn/start", "turn/steer"]}}},
            }}), encoding="utf-8")
            result = parse_schema_capabilities([path])
        self.assertEqual(result.status("app_server.thread.create"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(result.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(result.status("app_server.turn.steer"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertNotIn("not-a-rpc/method", result.schema_snapshot.discovered_methods)

    def test_json_schema_method_const_and_enum_are_normalized_without_text_false_positives(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "generated.json"
            path.write_text(json.dumps({"properties": {
                "method": {"const": "thread/start", "description": "not-a-rpc/method"},
                "notification": {"properties": {"method": {"enum": ["turn/start", "turn/steer"]}}},
            }}), encoding="utf-8")
            result = parse_schema_capabilities([path])
        self.assertEqual(result.status("app_server.thread.create"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(result.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(result.status("app_server.turn.steer"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertNotIn("not-a-rpc/method", result.schema_snapshot.discovered_methods)

    def test_approval_capability_uses_only_real_server_request_methods(self):
        self.assertEqual(FEATURE_METHODS["app_server.approvals"], (
            "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
            "item/permissions/requestApproval"))
        base = AppServerCapabilitySet({key: CapabilityStatus.SUPPORTED_WITH_LIMITATIONS for key in FEATURE_METHODS}, "fixture")
        one_request = base.confirm_runtime_method("item/fileChange/requestApproval")
        self.assertEqual(one_request.status("app_server.approvals"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        all_requests = one_request.confirm_runtime_method("item/commandExecution/requestApproval").confirm_runtime_method(
            "item/permissions/requestApproval")
        self.assertEqual(all_requests.status("app_server.approvals"), CapabilityStatus.SUPPORTED)

    def test_preflight_invokes_installed_schema_command_and_reads_output(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            fake = root / "fake_codex.py"
            fake.write_text(
                "import json, pathlib, sys\n"
                "out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "(out / 'rpc.json').write_text(json.dumps({'methods': [\n"
                " {'method': 'thread/start'}, {'method': 'turn/start'}]}))\n",
                encoding="utf-8",
            )
            result = discover_app_server_capabilities(command=[sys.executable, str(fake)], timeout=3)
        self.assertEqual(result.source, "GENERATED_LOCAL_SCHEMA")
        self.assertEqual(result.status("app_server.thread.create"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(result.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertEqual(result.status("app_server.turn.steer"), CapabilityStatus.UNSUPPORTED)

    def test_schema_generation_uses_and_cleans_managed_explicit_parent(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            fake = root / "fake_codex.py"
            fake.write_text(
                "import json, pathlib, sys\n"
                "out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "(out / 'rpc.json').write_text(json.dumps({'methods': [\n"
                " {'method': 'thread/start'}, {'method': 'turn/start'}]}))\n",
                encoding="utf-8",
            )
            owner_paths: list[Path] = []
            original_factory = temporary_directory

            def tracked_factory(namespace: str, parent=None, **kwargs):
                owner = original_factory(namespace, parent=parent, **kwargs)
                owner_paths.append(owner.path)
                return owner

            with patch("p4_codex_bridge.app_server_capabilities.temporary_directory", tracked_factory), \
                    patch("p4_codex_bridge.app_server_capabilities.tempfile.gettempdir", return_value=str(root)):
                result = discover_app_server_capabilities(command=[sys.executable, str(fake)], timeout=3)
            self.assertEqual(result.source, "GENERATED_LOCAL_SCHEMA")
            self.assertEqual(len(owner_paths), 1)
            self.assertFalse(owner_paths[0].exists())
            self.assertEqual(set(root.iterdir()), {fake})

    def test_schema_generator_failure_keeps_features_unknown(self):
        with TemporaryDirectory() as temp:
            fake = Path(temp) / "fake_codex.py"
            fake.write_text("import sys; sys.exit(7)\n", encoding="utf-8")
            result = discover_app_server_capabilities(command=[sys.executable, str(fake)], timeout=3)
        self.assertEqual(result.error, "schema_generator_failed")
        self.assertTrue(all(status == CapabilityStatus.UNKNOWN for status in result.statuses.values()))

    def test_schema_snapshot_is_compact_and_hash_stable(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "methods.json"
            path.write_text(json.dumps({"methods": [{"method": "thread/start"}, {"method": "turn/start"}]}), encoding="utf-8")
            first = parse_schema_capabilities([path], codex_version="codex-cli 0.160.1")
            second = parse_schema_capabilities([path], codex_version="codex-cli 0.160.1")
        snapshot = first.schema_snapshot
        self.assertIsInstance(snapshot, AppServerSchemaSnapshot)
        self.assertEqual(snapshot.source_type, "GENERATED_LOCAL_SCHEMA")
        self.assertEqual(snapshot.codex_version, "codex-cli 0.160.1")
        self.assertEqual(snapshot.source_identity, second.schema_snapshot.source_identity)
        self.assertIn("thread/start", snapshot.discovered_methods)

    def test_successful_runtime_method_promotes_only_its_capability(self):
        base = AppServerCapabilitySet({key: CapabilityStatus.SUPPORTED_WITH_LIMITATIONS for key in FEATURE_METHODS}, "GENERATED_LOCAL_SCHEMA")
        observed = base.confirm_runtime_method("thread/start")
        self.assertEqual(observed.status("app_server.thread.create"), CapabilityStatus.SUPPORTED)
        self.assertEqual(observed.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        missing = base.reject_runtime_method("turn/steer")
        self.assertEqual(missing.status("app_server.turn.steer"), CapabilityStatus.UNSUPPORTED)

    def test_renamed_method_does_not_claim_support_and_extra_method_is_ignored(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "schema.json"
            path.write_text(json.dumps({"methods": [{"method": "thread/create"},
                {"method": "turn/start"}, {"method": "future/unknown"}]}), encoding="utf-8")
            result = parse_schema_capabilities([path])
        self.assertEqual(result.status("app_server.thread.create"), CapabilityStatus.UNSUPPORTED)
        self.assertEqual(result.status("app_server.turn.start"), CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
        self.assertNotIn("future/unknown", FEATURE_METHODS)

    def test_malformed_and_empty_schema_preserve_unknown(self):
        with TemporaryDirectory() as temp:
            malformed = Path(temp) / "bad.json"
            malformed.write_text("{", encoding="utf-8")
            broken = parse_schema_capabilities([malformed])
            empty = parse_schema_capabilities([])
        self.assertTrue(all(status == CapabilityStatus.UNKNOWN for status in broken.statuses.values()))
        self.assertTrue(all(status == CapabilityStatus.UNKNOWN for status in empty.statuses.values()))
        self.assertIsNone(empty.schema_snapshot.source_identity)

    def test_unknown_feature_is_not_treated_as_supported(self):
        caps = AppServerCapabilitySet({}, "unavailable")
        with self.assertRaises(CapabilityUnavailableError):
            caps.require("app_server.turn.steer")

    def test_compatibility_keeps_unknown_separate_from_unsupported(self):
        caps = CapabilitySet({"app_server": {"thread": {"create": {"status": "SUPPORTED"}}}})
        result = assess_compatibility(CodexVersionInfo.parse("codex-cli 0.160.1"), caps,
            required=("app_server.thread.create", "app_server.turn.start"))
        self.assertEqual(result.status, CompatibilityStatus.UNKNOWN_NEWER_VERSION)
        self.assertFalse(result.missing_capabilities)
        self.assertIn("app_server.turn.start", result.unknown_capabilities)


if __name__ == "__main__":
    unittest.main()
