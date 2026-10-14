from __future__ import annotations

import subprocess
import sys
import importlib.util
from tests_py._portable_temp import TemporaryDirectory
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tests_real" / "smoke_live_watch.py"
SERVICE_SMOKE = ROOT / "tests_real" / "smoke_service.py"


class RealSmokeScriptTests(unittest.TestCase):
    def test_all_manual_smoke_scripts_document_help_without_inference(self) -> None:
        paths = sorted((ROOT / "tests_real").glob("smoke_*.py"))
        self.assertGreaterEqual(len(paths), 10)
        for script in paths:
            with self.subTest(script=script.name):
                result = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    cwd=ROOT, capture_output=True, text=True,
                    timeout=15, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout.lower())
                self.assertIn("--help", result.stdout)

    def test_live_manual_smokes_are_never_authorized_by_default(self) -> None:
        live_scripts = (
            "smoke_approval_reject.py",
            "smoke_concurrency.py",
            "smoke_live_watch.py",
            "smoke_persistent_thread.py",
            "smoke_runtime_approval.py",
            "smoke_runtime_manager.py",
            "smoke_streaming.py",
            "smoke_structured_output.py",
        )
        for name in live_scripts:
            with self.subTest(script=name):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tests_real" / name)],
                    cwd=ROOT, capture_output=True, text=True,
                    timeout=15, check=False,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("live inference disabled by default", result.stderr)

    def test_fake_scheduler_example_has_side_effect_free_help(self) -> None:
        script = ROOT / "examples" / "scheduler_demo.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=ROOT, capture_output=True, text=True,
            timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--state-dir", result.stdout)
        self.assertIn("--help", result.stdout)

    def test_python_api_smoke_is_opt_in_and_exposes_help(self) -> None:
        command = [sys.executable, str(ROOT / "tests_real" / "smoke_codex.py")]
        help_result = subprocess.run(
            [*command, "--help"], cwd=ROOT, capture_output=True,
            text=True, timeout=15, check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--run-real-turn", help_result.stdout)
        self.assertIn("--help", help_result.stdout)

        no_auth = subprocess.run(
            command, cwd=ROOT, capture_output=True,
            text=True, timeout=15, check=False,
        )
        self.assertEqual(no_auth.returncode, 2)
        self.assertIn("live inference disabled by default", no_auth.stderr)
        self.assertNotIn("codex", no_auth.stdout.lower())

    def test_live_watch_script_bootstraps_project_import_when_run_by_path(self) -> None:
        code = (
            "import pathlib, sys; "
            "root = pathlib.Path(sys.argv[1]).resolve(); "
            "sys.path = [p for p in sys.path if pathlib.Path(p or '.').resolve() != root]; "
            "scope = {'__name__': 'smoke_live_watch_import_check', '__file__': sys.argv[2]}; "
            "exec(compile(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'), sys.argv[2], 'exec'), scope); "
            "assert 'CodexBridge' in scope"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(ROOT), str(SMOKE)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_service_smoke_uses_installed_cross_process_client_contract(self) -> None:
        code = (
            "import pathlib, sys; "
            "root = pathlib.Path(sys.argv[1]).resolve(); "
            "sys.path = [p for p in sys.path if pathlib.Path(p or '.').resolve() != root]; "
            "scope = {'__name__': 'smoke_service_import_check', '__file__': sys.argv[2]}; "
            "exec(compile(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'), sys.argv[2], 'exec'), scope); "
            "assert scope['MODEL_ID'] == 'gpt-6-luna'; "
            "assert '_service_client_call' in scope"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(ROOT), str(SERVICE_SMOKE)],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_service_smoke_config_uses_valid_logging_section(self) -> None:
        from p4_codex_bridge.service import ServiceConfig

        spec = importlib.util.spec_from_file_location("service_smoke_config_check", SERVICE_SMOKE)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with TemporaryDirectory(prefix="p4-smoke-config-test-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            config = ServiceConfig.load(module._write_service_config(root, workspace),
                                        state_dir=root / "isolated-state")
            self.assertEqual(config.log_dir, (root / "logs").resolve())
            self.assertEqual(config.cwd, workspace.resolve())


if __name__ == "__main__":
    unittest.main()
