from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


_SECRET_PATTERNS = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"\b(OPENAI_API_KEY|CODEX_API_KEY|API_KEY|ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD|SECRET)\s*[:=]\s*[^\s,;]+", re.IGNORECASE), r"\1=[REDACTED]"),
    (re.compile(r"([\"']?(?:access[_-]?token|refresh[_-]?token|api[_-]?key|password|secret|cookie|credential)[\"']?\s*:\s*[\"']?)[^\s,\"'}]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED_JWT]"),
)


def redact(value: str | None) -> str:
    text = value or ""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_structured(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if re.search(r"token|secret|password|credential|cookie|api.?key", str(key), re.IGNORECASE):
                clean[key] = "[REDACTED]"
            else:
                clean[key] = redact_structured(item)
        return clean
    if isinstance(value, list):
        return [redact_structured(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def codex_environment() -> dict[str, str]:
    names = (
        "PATH", "PATHEXT", "SystemRoot", "WINDIR", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "CODEX_HOME", "TEMP", "TMP", "HOME", "P4_CODEX_BRIDGE_CODEX_EXECUTABLE",
    )
    return {name: os.environ[name] for name in names if name in os.environ}


def resolve_codex_command() -> list[str]:
    override = os.environ.get("P4_CODEX_BRIDGE_CODEX_EXECUTABLE")
    if override:
        path = Path(override)
        if path.suffix.lower() in {".py", ".js"}:
            if not path.is_file():
                raise FileNotFoundError("Codex executable not found")
            return [sys.executable if path.suffix.lower() == ".py" else shutil.which("node") or "node", str(path.resolve())]
        if os.path.sep in override and not path.is_file():
            raise FileNotFoundError("Codex executable not found")
        return [override]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        script = Path(entry) / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if script.is_file():
            node = shutil.which("node") or "node"
            return [node, str(script)]
    executable = shutil.which("codex")
    if executable:
        if executable.lower().endswith((".cmd", ".bat", ".ps1")):
            raise FileNotFoundError("Codex shell shim found but its executable JS package could not be resolved")
        return [executable]
    raise FileNotFoundError("Codex executable not found")


def build_exec_argv(
    request: dict[str, Any], schema_path: str | None = None,
    last_message_path: str | None = None,
) -> list[str]:
    operation = request.get("operation", "run")
    argv = resolve_codex_command()
    if operation == "run":
        skip_git_repo_check = request.get("skip_git_repo_check", False)
        if type(skip_git_repo_check) is not bool:
            raise ValueError("skip_git_repo_check must be a boolean")
        argv.extend([
            "--ask-for-approval", request["permissions"]["approval_policy"],
            "exec",
        ])
        if skip_git_repo_check:
            argv.append("--skip-git-repo-check")
        argv.extend([
            "--json", "--ephemeral", "--sandbox", request["permissions"]["sandbox"],
            "-C", request["cwd"],
        ])
        for root in request.get("writable_roots", []):
            argv.extend(["--add-dir", root])
    elif operation in {"resume", "fork"}:
        argv.extend(["exec", operation, request["session_id"], "--json"])
    elif operation == "review":
        argv.extend(["exec", "review"])
        if request.get("review_uncommitted"):
            argv.append("--uncommitted")
        if request.get("review_base"):
            argv.extend(["--base", request["review_base"]])
        if request.get("review_commit"):
            argv.extend(["--commit", request["review_commit"]])
        if request.get("review_title"):
            argv.extend(["--title", request["review_title"]])
        argv.append("--json")
    else:
        raise ValueError("unsupported Codex exec operation")
    if request.get("config_policy") == "isolated":
        argv.append("--ignore-user-config")
    model = request.get("model")
    if model:
        argv.extend(["--model", model])
    config_overrides = dict(request.get("config_overrides", {}))
    if request.get("reasoning_effort"):
        config_overrides["model_reasoning_effort"] = request["reasoning_effort"]
    if request.get("reasoning_summary"):
        config_overrides["model_reasoning_summary"] = request["reasoning_summary"]
    if request.get("verbosity"):
        config_overrides["model_verbosity"] = request["verbosity"]
    if request.get("network_access") is not None:
        config_overrides["sandbox_workspace_write.network_access"] = request["network_access"]
    for key, value in config_overrides.items():
        argv.extend(["-c", f"{key}={_toml_scalar(value)}"])
    if schema_path:
        argv.extend(["--output-schema", schema_path])
    if last_message_path:
        argv.extend(["--output-last-message", last_message_path])
    if request.get("prompt") or operation in {"run", "resume", "fork"}:
        argv.append("-")
    return argv


def _toml_scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise ValueError("config override values must be TOML scalar values or scalar lists")


def parse_exec_output(stdout: bytes, structured: bool, last_message: str | None = None) -> tuple[str, Any, str | None]:
    content = last_message if last_message is not None else ""
    if last_message is None:
        content = ""
        for line in stdout.decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message":
                content = event["item"].get("text", "")
    parsed = None
    if structured and content.strip():
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content, None, "Codex final message did not match JSON output"
    return content, parsed, None


def extract_session_id(stdout: bytes) -> str | None:
    for line in stdout.decode("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            value = event.get("thread_id")
            if isinstance(value, str) and value:
                return value
    return None


def probe(args: list[str], *, timeout: float = 10) -> str:
    completed = subprocess.run(
        resolve_codex_command() + args,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=codex_environment(),
        check=False,
    )
    return completed.stdout + completed.stderr
