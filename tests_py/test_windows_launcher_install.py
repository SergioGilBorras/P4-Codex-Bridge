"""Opt-in wheel/console-launcher integration test (no Codex inference)."""
from __future__ import annotations

import os
import ctypes
import struct
import subprocess
import sys
from tests_py._portable_temp import TemporaryDirectory
import unittest
from pathlib import Path


def _run_console_launcher_in_job(executable: Path, args: tuple[str, ...], cwd: Path, log_prefix: Path, timeout: float = 15):
    """Run an owned launcher tree in a kill-on-close Windows Job Object."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID), ("bInheritHandle", wintypes.BOOL)]

    class StartupInfo(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class ProcessInformation(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInformation)]
    kernel.CreateProcessW.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    def check(ok, label):
        if not ok:
            raise OSError(ctypes.get_last_error(), label)

    sa = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
    out_path, err_path = str(log_prefix.with_suffix(".out")), str(log_prefix.with_suffix(".err"))
    out_handle = kernel.CreateFileW(out_path, 0x40000000, 0x00000007, ctypes.byref(sa), 2, 0x80, None)
    err_handle = kernel.CreateFileW(err_path, 0x40000000, 0x00000007, ctypes.byref(sa), 2, 0x80, None)
    job = kernel.CreateJobObjectW(None, None)
    process = ProcessInformation()
    assigned = False
    try:
        check(out_handle not in (0, -1), "CreateFile stdout")
        check(err_handle not in (0, -1), "CreateFile stderr")
        check(job not in (0, -1), "CreateJobObject")
        # JOB_OBJECT_EXTENDED_LIMIT_INFORMATION on 64-bit Windows is 144 bytes;
        # LimitFlags is the DWORD at offset 16 in its BASIC_LIMIT_INFORMATION.
        limits = ctypes.create_string_buffer(144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112)
        struct.pack_into("I", limits, 16, 0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        check(kernel.SetInformationJobObject(job, 9, limits, len(limits)), "SetInformationJobObject")
        startup = StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = 0x100  # STARTF_USESTDHANDLES
        startup.hStdInput = kernel.GetStdHandle(-10)
        startup.hStdOutput = out_handle
        startup.hStdError = err_handle
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(executable), *args]))
        created = kernel.CreateProcessW(str(executable), command_line, None, None, True,
            0x4 | 0x08000000, None, str(cwd), ctypes.byref(startup), ctypes.byref(process))
        check(created, "CreateProcess launcher")
        check(kernel.AssignProcessToJobObject(job, process.hProcess), "AssignProcessToJobObject")
        assigned = True
        check(kernel.ResumeThread(process.hThread) != 0xFFFFFFFF, "ResumeThread")
        wait_result = kernel.WaitForSingleObject(process.hProcess, int(timeout * 1000))
        timed_out = wait_result == 0x102
        if timed_out:
            kernel.TerminateJobObject(job, 124)
            kernel.WaitForSingleObject(process.hProcess, 5000)
        exit_code = wintypes.DWORD()
        check(kernel.GetExitCodeProcess(process.hProcess, ctypes.byref(exit_code)), "GetExitCodeProcess")
        return int(exit_code.value), timed_out, Path(out_path).read_text(encoding="utf-8", errors="replace"), Path(err_path).read_text(encoding="utf-8", errors="replace")
    finally:
        if process.hProcess and not assigned:
            kernel.TerminateProcess(process.hProcess, 125)
            kernel.WaitForSingleObject(process.hProcess, 5000)
        if process.hThread:
            kernel.CloseHandle(process.hThread)
        if process.hProcess:
            kernel.CloseHandle(process.hProcess)
        if job:
            kernel.CloseHandle(job)  # kills any remaining descendants in our job
        if out_handle not in (0, -1):
            kernel.CloseHandle(out_handle)
        if err_handle not in (0, -1):
            kernel.CloseHandle(err_handle)


@unittest.skipUnless(os.name == "nt" and os.environ.get("P4_RUN_WINDOWS_LAUNCHER_TESTS") == "1",
                     "set P4_RUN_WINDOWS_LAUNCHER_TESTS=1 on Windows to build/install/test the exe shim")
class WindowsWheelLauncherTests(unittest.TestCase):
    def test_wheel_console_commands_exit_and_venv_is_removable(self):
        from p4_codex_bridge import __version__
        project = Path(__file__).resolve().parents[1]
        temp = TemporaryDirectory(prefix="p4-codex-launcher-")
        root = Path(temp.name)
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()
        venv = root / "venv with spaces"
        config = root / "minimal.toml"
        state = root / "state dir"
        config.write_text(f'[service]\ncwd = "{project.as_posix()}"\n', encoding="utf-8")
        def stage(name: str) -> None:
            sys.stderr.write(f"[windows-launcher-test] {name}\n")
            sys.stderr.flush()
        try:
            stage("build-wheel")
            subprocess.run([sys.executable, "-m", "pip", "wheel", str(project), "--no-deps",
                "--no-build-isolation", "--wheel-dir", str(wheelhouse)], check=True, timeout=120,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
            wheel = next(wheelhouse.glob("p4_codex_bridge-*.whl"))
            stage("create-venv")
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=60,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
            python = venv / "Scripts" / "python.exe"
            executable = venv / "Scripts" / "p4-codex.exe"
            stage("install-wheel")
            subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], check=True,
                timeout=120, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
            self.assertTrue(executable.is_file())
            for args in (("--version",), ("--help",), ("config", "validate", "--config", str(config), "--state-dir", str(state)),
                         ("service", "status", "--config", str(config), "--state-dir", str(state), "--json")):
                with self.subTest(args=args):
                    stage("launcher " + " ".join(args))
                    code, timed_out, stdout, stderr = _run_console_launcher_in_job(executable, args, project, root / ("cmd-" + str(len(args))))
                    self.assertFalse(timed_out, f"launcher timed out; stdout={stdout!r}, stderr={stderr!r}")
                    self.assertIn(code, (0, 1), stderr)
                    if args == ("--version",):
                        self.assertIn(__version__, stdout)
                    if args == ("--help",):
                        self.assertIn("usage: p4-codex", stdout.lower())
            self.assertFalse((state / "runs.sqlite3").exists(), "version/help/config/status must not start a service DB")
        finally:
            try:
                temp.cleanup()
            except PermissionError as exc:
                self.fail(f"wheel test left an open handle in its venv/temp directory: {exc}")


if __name__ == "__main__":
    unittest.main()
