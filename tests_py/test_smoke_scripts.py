from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tests_real" / "smoke_live_watch.py"


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


if __name__ == "__main__":
    unittest.main()
