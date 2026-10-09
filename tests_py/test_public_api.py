import unittest
import inspect

import p4_codex_bridge as bridge


class PublicApiFreezeTests(unittest.TestCase):
    def test_stable_facade_exports_are_present(self):
        expected = {
            "CodexBridge", "CodexServiceClient", "ExecRunSubmission",
            "CreateThreadRequest", "StartTurnRequest", "CommandResult",
            "CodexPermissions", "RunSecurityPolicy", "ProjectTrust",
            "SecurityDecision", "SecurityDecisionResult", "validate_run_security",
            "CodexVersionInfo", "CapabilitySet", "CompatibilityResult",
            "CompatibilityStatus", "assess_compatibility", "CapabilityStatus", "AppServerCapabilityStatus",
            "AppServerCapabilitySet", "ApprovalRequest", "CodexEvent",
            "ApprovalError", "ApprovalTimeoutError", "ApprovalRejectedError",
            "EventStreamError", "EventDecodeError", "ToolEventError",
            "RunResult", "BridgeRun", "RunStatus", "ConfigPolicy",
            "SandboxMode", "ApprovalPolicy", "ApprovalHandlingPolicy",
            "AppServerApprovalPolicy", "CodexTurn", "BridgeError",
            "ConfigurationError", "CapabilityUnavailableError",
            "ServiceUnavailableError", "ConflictError",
            "RunSecurityRejectedError", "CapabilityIsolationUnavailableError",
            "QueueFullError", "ResourceUnavailableError", "RunNotFoundError",
            "RunStateError", "BackendError", "AuthenticationError",
            "ProtocolError", "BridgeTimeoutError", "__version__",
        }
        self.assertEqual(set(bridge.__all__), expected)
        for name in expected:
            self.assertTrue(hasattr(bridge, name), name)

    def test_implementation_details_are_not_package_root_exports(self):
        internal = {
            "CodexRuntimeManager", "ResourceScheduler", "RunRegistry",
            "AppServerConnection", "ForegroundService", "ServiceConfig",
            "SQLiteRegistry", "discover_app_server_capabilities",
        }
        self.assertTrue(internal.isdisjoint(bridge.__all__))
        for name in internal:
            with self.assertRaises(AttributeError):
                getattr(bridge, name)

    def test_stable_run_signature_is_explicit_and_closed(self):
        parameters = inspect.signature(bridge.CodexBridge.run).parameters
        self.assertEqual(list(parameters), [
            "self", "prompt", "cwd", "profile", "model", "timeout_seconds", "permissions",
            "reasoning_effort", "reasoning_summary", "verbosity", "output_schema",
            "skip_git_repo_check", "capture_last_message", "include_raw_output", "config_policy", "config_overrides",
            "metadata", "announce_run", "security_policy",
        ])
        self.assertFalse(any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()))

    def test_run_and_start_skip_git_option_is_typed_and_disabled_by_default(self):
        for method in (bridge.CodexBridge.run, bridge.CodexBridge.start):
            parameter = inspect.signature(method).parameters["skip_git_repo_check"]
            self.assertEqual(parameter.default, False)
            self.assertIn(str(parameter.annotation), {"bool", "<class 'bool'>"})

    def test_public_runtime_manager_remains_internal(self):
        self.assertNotIn("CodexRuntimeManager", bridge.__all__)

    def test_generic_and_app_server_capability_statuses_are_unambiguous(self):
        self.assertIsNot(bridge.CapabilityStatus, bridge.AppServerCapabilityStatus)
        self.assertEqual(bridge.CapabilityStatus.UNKNOWN.value, "UNKNOWN")
        self.assertEqual(bridge.AppServerCapabilityStatus.UNKNOWN.value, "UNKNOWN")

if __name__ == "__main__":
    unittest.main()
