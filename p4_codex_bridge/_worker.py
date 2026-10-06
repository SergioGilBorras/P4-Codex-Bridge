from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RunStatus
from .registry import RunRegistry
from .runtime import build_exec_argv, codex_environment, extract_session_id, parse_exec_output, redact, redact_structured

MAX_OUTPUT_BYTES = 4 * 1024 * 1024
_STOP_REQUESTED = threading.Event()


def _identity(pid: int) -> str:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
        )
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            raise OSError("cannot inspect process identity")
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        try:
            if not kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
                raise OSError("cannot inspect process identity")
            return f"{creation.dwHighDateTime:08x}{creation.dwLowDateTime:08x}"
        finally:
            kernel32.CloseHandle(handle)
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    return stat.rsplit(")", 1)[1].split()[19]


def _terminate_tree(pid: int, *, force: bool) -> None:
    if os.name == "nt":
        if not force:
            try:
                os.kill(pid, signal.CTRL_BREAK_EVENT)
                return
            except (OSError, ProcessLookupError):
                pass
        args = ["taskkill.exe", "/PID", str(pid), "/T"] + (["/F"] if force else [])
        completed = subprocess.run(args, shell=False, capture_output=True, env=codex_environment(), check=False)
        if completed.returncode != 0:
            try:
                os.kill(pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
    else:
        os.killpg(pid, signal.SIGKILL if force else signal.SIGINT)


def _read_limited(stream: Any, output: bytearray, lock: threading.Lock, exceeded: threading.Event, event_sink: Any = None) -> None:
    pending = bytearray()
    while True:
        chunk = stream.read(65536)
        if not chunk:
            if pending and event_sink:
                event_sink(bytes(pending))
            return
        if event_sink:
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, remainder = pending.partition(b"\n")
                pending = bytearray(remainder)
                if line: event_sink(bytes(line))
        with lock:
            if len(output) + len(chunk) > MAX_OUTPUT_BYTES:
                exceeded.set()
                remaining = max(0, MAX_OUTPUT_BYTES - len(output))
                output.extend(chunk[:remaining])
            elif not exceeded.is_set():
                output.extend(chunk)


def execute(registry: RunRegistry, run_id: str, request: dict[str, Any]) -> None:
    raw = registry.raw(run_id)
    if raw is None:
        return
    started = time.monotonic()
    schema_path = None
    last_message_path = None
    temporary_paths: list[str] = []

    def cleanup_temporary_files() -> None:
        for item in temporary_paths:
            Path(item).unlink(missing_ok=True)

    if request.get("output_schema") is not None:
        schema_dir = Path(request["state_dir"]) / "temp"
        schema_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", dir=schema_dir, delete=False) as schema_file:
            json.dump(request["output_schema"], schema_file, ensure_ascii=False)
            schema_path = schema_file.name
            temporary_paths.append(schema_path)
    if request.get("capture_last_message"):
        temp_dir = Path(request["state_dir"]) / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", dir=temp_dir, delete=False) as output_file:
            last_message_path = output_file.name
            temporary_paths.append(last_message_path)
        Path(last_message_path).unlink()
    try:
        argv = build_exec_argv(request, schema_path, last_message_path)
    except FileNotFoundError:
        cleanup_temporary_files()
        _write_failure(raw["result_path"], run_id, "CODEX_NOT_FOUND", "Codex executable not found")
        registry.update(run_id, status=RunStatus.FAILED.value, last_error="Codex executable not found")
        return
    except (TypeError, ValueError):
        cleanup_temporary_files()
        _write_failure(raw["result_path"], run_id, "CODEX_REQUEST_INVALID", "Codex operation request is invalid")
        registry.update(run_id, status=RunStatus.FAILED.value, last_error="Codex operation request is invalid")
        return
    options: dict[str, Any] = {
        "args": argv,
        "cwd": request["cwd"],
        "env": codex_environment(),
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "text": False,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        options["startupinfo"] = subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESHOWWINDOW)
    else:
        options["start_new_session"] = True
    try:
        child = subprocess.Popen(**options)
    except FileNotFoundError:
        cleanup_temporary_files()
        registry.update(run_id, status=RunStatus.FAILED.value, exit_code=None, last_error="Codex executable not found")
        return
    except OSError:
        cleanup_temporary_files()
        registry.update(run_id, status=RunStatus.FAILED.value, exit_code=None, last_error="Codex could not be started")
        return

    try:
        child_identity = _identity(child.pid)
        registry.update(run_id, pid=child.pid, pid_identity=child_identity, status=RunStatus.RUNNING.value)
        if request.get("managed_scheduled"):
            from .scheduler import ResourceScheduler
            ResourceScheduler(registry.path).set_process(run_id, process_pid=child.pid, process_identity=child_identity)
        registry.add_run_event(run_id, "ResourceAcquired", {"backend": "exec", "pid": child.pid})
    except OSError:
        child.kill()
        cleanup_temporary_files()
        registry.update(run_id, status=RunStatus.FAILED.value, last_error="Could not verify child process identity")
        return

    stdout = bytearray()
    stderr = bytearray()
    lock = threading.Lock()
    exceeded = threading.Event()
    def record_exec_event(line: bytes) -> None:
        try: event = json.loads(line.decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeError): return
        if not isinstance(event, dict): return
        kind = event.get("type")
        if kind == "thread.started":
            native_id = event.get("thread_id")
            if isinstance(native_id, str):
                registry.update(run_id, session_id=native_id, thread_id=native_id)
                if request.get("managed_scheduled"):
                    from .scheduler import ResourceScheduler
                    ResourceScheduler(registry.path).set_process(run_id, native_session_id=native_id)
                registry.add_run_event(run_id, "ThreadStarted", {"thread_id": native_id})
        elif kind == "turn.started":
            native_turn = event.get("turn_id") or (event.get("turn", {}).get("id") if isinstance(event.get("turn"), dict) else None)
            if isinstance(native_turn, str):
                registry.update(run_id, turn_id=native_turn)
                registry.add_run_event(run_id, "TurnStarted", {"turn_id": native_turn})
        elif kind == "turn.completed":
            turn = event.get("turn") if isinstance(event.get("turn"), dict) else {}
            registry.add_run_event(run_id, "TurnCompleted", {"status": turn.get("status"), "usage": turn.get("usage") or event.get("usage")})
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        if kind == "item.completed" and item.get("type") == "agent_message":
            registry.add_run_event(run_id, "AgentMessageCompleted", {"final_text": item.get("text", "")})
        elif kind in {"item.started", "item.completed"} and item.get("type") in {"command_execution", "file_change", "mcp_tool_call"}:
            registry.add_run_event(run_id, "ToolStarted" if kind == "item.started" else "ToolCompleted", {"item_type": item.get("type"), "tool": item.get("name") or item.get("command"), "status": item.get("status")})
    readers = [
        threading.Thread(target=_read_limited, args=(child.stdout, stdout, lock, exceeded, record_exec_event), daemon=True),
        threading.Thread(target=_read_limited, args=(child.stderr, stderr, lock, exceeded), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        prompt = request["prompt"]
        if request.get("operation", "run") == "run" and request["profile"] == "analysis":
            prompt = "P4-Codex-Bridge profile: analysis. Provide analysis only; do not intentionally modify files or use Jira or external services.\n\n" + prompt
        child.stdin.write(prompt.encode("utf-8"))
        child.stdin.close()
    except (BrokenPipeError, OSError):
        pass

    terminal = RunStatus.COMPLETED
    deadline = started + request["timeout_seconds"]
    while child.poll() is None:
        if _STOP_REQUESTED.is_set() or Path(request["stop_path"]).exists():
            terminal = RunStatus.CANCELLED if request.get("managed_scheduled") and request.get("cancel_path") and Path(request["cancel_path"]).exists() else RunStatus.STOPPED
            _terminate_tree(child.pid, force=False)
            break
        if exceeded.is_set():
            terminal = RunStatus.FAILED
            _terminate_tree(child.pid, force=True)
            break
        if time.monotonic() >= deadline:
            terminal = RunStatus.TIMED_OUT
            _terminate_tree(child.pid, force=True)
            break
        time.sleep(0.04)
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate_tree(child.pid, force=True)
        child.wait()
    for reader in readers:
        reader.join(timeout=2)

    exit_code = child.returncode
    last_message = None
    missing_last_message = False
    if last_message_path:
        if Path(last_message_path).is_file():
            try:
                if Path(last_message_path).stat().st_size > MAX_OUTPUT_BYTES:
                    exceeded.set()
                else:
                    last_message = Path(last_message_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                missing_last_message = exit_code == 0
        else:
            missing_last_message = exit_code == 0
    content, structured, parse_error = parse_exec_output(bytes(stdout), request.get("output_schema") is not None, last_message)
    error: str | None = parse_error
    error_code: str | None = "STRUCTURED_OUTPUT_INVALID" if parse_error else None
    if parse_error:
        terminal = RunStatus.FAILED
    if terminal == RunStatus.CANCELLED:
        error, error_code = "Codex run cancelled by caller", "CODEX_CANCELLED"
    elif terminal == RunStatus.STOPPED:
        error, error_code = "Codex run stopped by bridge", "CODEX_STOPPED"
    elif terminal == RunStatus.TIMED_OUT:
        error, error_code = "Codex run timed out", "CODEX_TIMEOUT"
    elif exceeded.is_set():
        error, error_code = "Codex output exceeded the configured limit", "CODEX_OUTPUT_LIMIT"
    elif exit_code != 0:
        safe_stderr = redact(bytes(stderr).decode("utf-8", "replace"))
        if any(term in safe_stderr.lower() for term in ("not logged in", "login required", "not authenticated")):
            error, error_code = "Codex ChatGPT login is required", "CODEX_AUTH_REQUIRED"
        else:
            error, error_code = "Codex CLI exited with a non-zero status", "CODEX_EXIT_NONZERO"
        terminal = RunStatus.FAILED
    elif missing_last_message:
        error, error_code, terminal = "Codex did not create the requested last-message file", "OUTPUT_LAST_MESSAGE_MISSING", RunStatus.FAILED
    elif not content.strip():
        error, error_code, terminal = "Codex returned no final message", "CODEX_EMPTY_RESPONSE", RunStatus.FAILED
    result = {
        "ok": terminal == RunStatus.COMPLETED and error is None,
        "bridge_run_id": run_id,
        "exit_code": exit_code,
        "content": redact(content),
        "stderr": redact(bytes(stderr).decode("utf-8", "replace").strip()),
        "structured_output": redact_structured(structured),
        "session_id": extract_session_id(bytes(stdout)),
        "raw_output": redact(bytes(stdout).decode("utf-8", "replace")) if request.get("include_raw_output") else None,
        "error": {"code": error_code, "message": redact(error)} if error else None,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    result_path = Path(raw["result_path"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_result = result_path.with_suffix(".tmp")
    temporary_result.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary_result.replace(result_path)
    cleanup_temporary_files()
    registry.update(
        run_id,
        status=terminal.value,
        exit_code=exit_code,
        last_error=redact(error) if error else None,
        session_id=result.get("session_id"),
    )
    if request.get("announce_run"):
        metadata = request.get("agent_metadata") if isinstance(request.get("agent_metadata"), dict) else {}
        status = "SUCCESS" if result.get("ok") else "FAILED"
        detail = "" if result.get("ok") else " | " + redact(str((result.get("error") or {}).get("message", "Codex run failed")))[:300]
        print(f"[P4-Codex] {'Completed' if result.get('ok') else 'Failed'} {run_id} | {status} | {int(result.get('duration_ms', 0))} ms{detail}", file=sys.stderr, flush=True)
    Path(request["stop_path"]).unlink(missing_ok=True)
    if request.get("cancel_path"):
        Path(request["cancel_path"]).unlink(missing_ok=True)


def _write_failure(result_path: str, run_id: str, code: str, message: str) -> None:
    path = Path(result_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "ok": False, "bridge_run_id": run_id, "exit_code": None,
        "content": "", "stderr": "", "structured_output": None,
        "error": {"code": code, "message": message}, "duration_ms": 0,
    }), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--result")
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        return 2
    request = json.loads(raw)
    registry = RunRegistry(args.db)
    worker_pid = os.getpid()
    worker_identity = _identity(worker_pid)
    registry.update(args.run_id, worker_pid=worker_pid, worker_identity=worker_identity)
    scheduled = bool(request.get("managed_scheduled"))
    scheduler = None
    if scheduled:
        from .scheduler import ResourceScheduler
        scheduler = ResourceScheduler(args.db)
        scheduler.set_process(args.run_id, worker_pid=worker_pid, worker_identity=worker_identity)
    signal.signal(signal.SIGINT, lambda _signum, _frame: _STOP_REQUESTED.set())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda _signum, _frame: _STOP_REQUESTED.set())
    if scheduled and request.get("cancel_path") and Path(request["cancel_path"]).exists():
        _write_failure(request["result_path"], args.run_id, "CODEX_CANCELLED", "Cancelled before execution started")
        registry.update(args.run_id, status=RunStatus.CANCELLED.value, last_error="Cancelled before execution started")
    else:
        try:
            execute(registry, args.run_id, request)
        except Exception as exc:
            _write_failure(request["result_path"], args.run_id, "BRIDGE_WORKER_ERROR", redact(str(exc))[:300])
            registry.update(args.run_id, status=RunStatus.FAILED.value, last_error="Bridge worker failed unexpectedly")
    if scheduled and scheduler:
        final = registry.raw(args.run_id) or {}
        status = final.get("status", RunStatus.FAILED.value)
        if status not in scheduler.TERMINAL:
            status = RunStatus.FAILED.value
            registry.update(args.run_id, status=status, last_error="Worker ended without a terminal status")
        scheduler.finish(args.run_id, status, finished_at=datetime.now(timezone.utc).isoformat(), error=final.get("last_error"))
        registry.add_run_event(args.run_id, status, {"exit_code": final.get("exit_code"), "last_error": final.get("last_error")})
        registry.add_run_event(args.run_id, "ResourceReleased", {})
        try:
            from .runtime_manager import notify_app_server_capacity_change
            notify_app_server_capacity_change(Path(args.db).resolve())
        except Exception:
            pass
        try:
            package_root = str(Path(__file__).resolve().parent.parent)
            env = codex_environment()
            env["PYTHONPATH"] = os.pathsep.join(filter(None, (package_root, env.get("PYTHONPATH", ""))))
            kwargs: dict[str, Any] = {"args": [sys.executable, "-m", "p4_codex_bridge._exec_dispatch", "--database", str(Path(args.db).resolve())],
                "cwd": package_root, "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL, "shell": False, "close_fds": True}
            if os.name == "nt": kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            else: kwargs["start_new_session"] = True
            subprocess.Popen(**kwargs)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
