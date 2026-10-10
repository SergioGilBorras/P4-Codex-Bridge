"""Offline wheel test for the supported Windows .cmd shortcut."""
from __future__ import annotations

import os
import importlib.util
import subprocess
import sys
from tests_py._portable_temp import TemporaryDirectory
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows .cmd launcher test")
class WindowsCmdLauncherTests(unittest.TestCase):
    def _build_wheel(self, project: Path, wheelhouse: Path) -> None:
        if importlib.util.find_spec("setuptools") is None or importlib.util.find_spec("wheel") is None:
            self.skipTest("setuptools and wheel are required for the offline wheel test; validate package build separately")
        command = [sys.executable, "-m", "pip", "wheel", str(project), "--no-deps",
                   "--no-build-isolation", "--wheel-dir", str(wheelhouse)]
        try:
            subprocess.run(command, check=True, timeout=120, capture_output=True,
                           text=True, shell=False)
        except subprocess.CalledProcessError as exc:
            # Some managed Windows environments deny pip's own build-tracker
            # temp files. Do not mask package/build errors; skip only that
            # precise host-temp permission failure, which is validated by the
            # separate isolated package-install check.
            diagnostic = exc.stderr or ""
            if "PermissionError" in diagnostic and "pip-build-tracker" in diagnostic:
                self.skipTest("host policy denied pip build-tracker temp access; package install is checked separately")
            # pip captures its diagnostics in CalledProcessError; include only
            # a bounded tail so CI reports the actual build failure.
            excerpt = diagnostic[-2000:]
            raise AssertionError(f"offline wheel build failed ({exc.returncode}): {excerpt}") from None

    def test_wrapper_contract_and_module_entrypoint(self):
        from p4_codex_bridge import __version__
        project = Path(__file__).resolve().parents[1]
        wrapper = (project / "bin" / "p4-codex.cmd").read_text(encoding="utf-8")
        self.assertIn('set "_P4_CODEX_PYTHON=%~dp0python.exe"', wrapper)
        self.assertIn('"%_P4_CODEX_PYTHON%" -m p4_codex_bridge %*', wrapper)
        self.assertIn("exit /b %ERRORLEVEL%", wrapper)
        self.assertNotIn(">out", wrapper.lower())
        self.assertNotIn(">nul", wrapper.lower())

        result = subprocess.run([sys.executable, "-m", "p4_codex_bridge", "--version"],
                                cwd=project, capture_output=True, text=True, timeout=10, shell=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"p4-codex {__version__}", result.stdout)

    def test_wheel_installs_cmd_beside_environment_python(self):
        from p4_codex_bridge import __version__
        project = Path(__file__).resolve().parents[1]
        with TemporaryDirectory(prefix="P4 wheel cmd ") as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            venv = root / "venv with spaces"
            self._build_wheel(project, wheelhouse)
            wheel = next(wheelhouse.glob("p4_codex_bridge-*.whl"))
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True,
                           timeout=60, capture_output=True, text=True, shell=False)
            python = venv / "Scripts" / "python.exe"
            subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], check=True,
                           timeout=120, capture_output=True, text=True, shell=False)
            launcher = venv / "Scripts" / "p4-codex.cmd"
            self.assertTrue(python.is_file())
            self.assertTrue(launcher.is_file())
            self.assertEqual(launcher.read_bytes(), (project / "bin" / "p4-codex.cmd").read_bytes())
            module = subprocess.run([str(python), "-m", "p4_codex_bridge", "--version"],
                                    cwd=root, capture_output=True, text=True, timeout=10, shell=False)
            self.assertEqual(module.returncode, 0, module.stderr)
            self.assertIn(f"p4-codex {__version__}", module.stdout)

    @unittest.skipUnless(os.environ.get("P4_RUN_WINDOWS_CMD_LAUNCHER_TESTS") == "1",
                         "set P4_RUN_WINDOWS_CMD_LAUNCHER_TESTS=1 outside restricted shells for installed CMD integration")
    def test_installed_cmd_quotes_paths_forwards_stdio_and_exit_code(self):
        from p4_codex_bridge import __version__
        project = Path(__file__).resolve().parents[1]
        with TemporaryDirectory(prefix="P4 bridge cmd ") as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            venv = root / "venv with spaces"
            self._build_wheel(project, wheelhouse)
            wheel = next(wheelhouse.glob("p4_codex_bridge-*.whl"))
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True,
                           timeout=60, capture_output=True, text=True, shell=False)
            python = venv / "Scripts" / "python.exe"
            subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], check=True,
                           timeout=120, capture_output=True, text=True, shell=False)

            launcher = venv / "Scripts" / "p4-codex.cmd"
            self.assertTrue(launcher.is_file(), "wheel must install the supported CMD launcher")
            self.assertTrue(python.is_file())
            comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")

            def invoke(*args: str) -> subprocess.CompletedProcess[str]:
                command = f'"{launcher}" {subprocess.list2cmdline(list(args))}'
                return subprocess.run([comspec, "/d", "/s", "/c", f'"{command}"'], cwd=root,
                                      capture_output=True, text=True, timeout=10, shell=False)

            version = invoke("--version")
            self.assertEqual(version.returncode, 0, version.stderr)
            self.assertIn(f"p4-codex {__version__}", version.stdout)

            help_result = invoke("--help")
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("usage: p4-codex", help_result.stdout.lower())

            invalid = invoke("--invalid-launcher-test-argument")
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("usage: p4-codex", invalid.stderr.lower())

            workspace = root / "workspace with spaces"
            workspace.mkdir()
            config = root / "config with spaces.toml"
            config.write_text(f'[service]\ncwd = "{workspace.as_posix()}"\n', encoding="utf-8")
            validated = invoke("config", "validate", "--config", str(config))
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn('"valid": true', validated.stdout.lower())


if __name__ == "__main__":
    unittest.main()
