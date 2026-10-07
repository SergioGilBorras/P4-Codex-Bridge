from __future__ import annotations

import subprocess
import sys
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tests_real" / "smoke_live_watch.py"
SERVICE_SMOKE = ROOT / "tests_real" / "smoke_service.py"


class RealSmokeScriptTests(unittest.TestCase):
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
        with tempfile.TemporaryDirectory(prefix="p4-smoke-config-test-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            config = ServiceConfig.load(module._write_service_config(root, workspace))
            self.assertEqual(config.log_dir, (root / "logs").resolve())
            self.assertEqual(config.cwd, workspace.resolve())


if __name__ == "__main__":
    unittest.main()
