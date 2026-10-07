import contextlib
import io
import json
import os
import tempfile
import unittest

from p4_codex_bridge.cli import _error_exit_code, build_parser, main
from p4_codex_bridge.errors import (BackendError, BridgeTimeoutError, CapabilityUnavailableError,
                                    ConflictError, RunSecurityRejectedError, ServiceUnavailableError)
from p4_codex_bridge.events import ApprovalError, EventStreamError


class CliContractTests(unittest.TestCase):
    def test_frozen_root_command_tree_and_json_leaf_contract(self):
        parser = build_parser()
        actions = next(action for action in parser._actions if action.dest == "command")
        expected = {"approvals", "approve", "cancel", "capabilities", "config", "doctor", "events",
                    "health", "inspect", "kill", "limits", "maintenance", "metrics", "models", "ps",
                    "reject", "resources", "result", "run", "service", "start", "status", "stop",
                    "submit", "thread", "turn", "version", "watch"}
        self.assertEqual(set(actions.choices), expected)

        def leaves(current):
            subparsers = [action for action in current._actions if hasattr(action, "choices") and action.choices]
            if not subparsers:
                return [current]
            return [leaf for action in subparsers for child in action.choices.values() for leaf in leaves(child)]

        for leaf in leaves(parser):
            self.assertTrue(any("--json" in action.option_strings for action in leaf._actions), leaf.prog)

    def test_exit_code_contract(self):
        self.assertEqual([_error_exit_code(exc) for exc in (
            RunSecurityRejectedError(), CapabilityUnavailableError(), ServiceUnavailableError(),
            BridgeTimeoutError(), BackendError(), ConflictError(), ValueError(),
            ApprovalError(), EventStreamError(),
        )], [3, 4, 5, 6, 7, 8, 2, 8, 7])
    def test_service_status_stdout_is_json_with_and_without_flag(self):
        previous = os.environ.get("P4_CODEX_BRIDGE_STATE_DIR")
        with tempfile.TemporaryDirectory() as state:
            try:
                workspace = state.replace("\\", "/")
                config = os.path.join(state, "bridge.toml")
                with open(config, "w", encoding="utf-8") as stream:
                    stream.write(f'[service]\ncwd = "{workspace}"\nstate_dir = "{workspace}/state"\n'
                                 f'[codex]\nallowed_roots = ["{workspace}"]\n')
                for suffix in ([], ["--json"]):
                    out, err = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        code = main(["service", "status", "--config", config,
                                     "--state-dir", os.path.join(state, "state"), *suffix])
                    self.assertEqual(code, 0)
                    self.assertEqual(json.loads(out.getvalue()) ["state"], "STOPPED")
                    self.assertEqual(err.getvalue(), "")
            finally:
                if previous is None:
                    os.environ.pop("P4_CODEX_BRIDGE_STATE_DIR", None)
                else:
                    os.environ["P4_CODEX_BRIDGE_STATE_DIR"] = previous

    def test_machine_command_leaf_accepts_json_flag(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as help_exit:
                main(["watch", "--help"])
        self.assertEqual(help_exit.exception.code, 0)
        self.assertIn("--json", out.getvalue())

    def test_validation_failure_emits_one_json_record_and_sanitized_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["config", "validate", "--config", "Z:\\missing\\bridge.toml", "--json"])
        self.assertEqual(code, 2)
        rows = out.getvalue().splitlines()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "VALIDATION_ERROR")
        self.assertTrue(err.getvalue())

    def test_usage_failure_is_json_on_stdout_with_exit_two(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                main(["not-a-command"])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "USAGE_ERROR")
        self.assertEqual(err.getvalue(), "invalid command arguments\n")


if __name__ == "__main__":
    unittest.main()
