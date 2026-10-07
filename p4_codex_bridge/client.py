from __future__ import annotations

import json
import asyncio
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from ._worker import _identity, _terminate_tree
from .events import ApprovalError
from .errors import CapabilityUnavailableError
from .models import (
    AppServerApprovalPolicy, ApprovalHandlingPolicy, ApprovalPolicy, BridgeRun,
    ConfigPolicy, ModelVerbosity, ReasoningSummary, RunResult, RunStatus, SandboxMode,
)
from .permissions import CodexPermissions, CwdPolicy
from .security import RunSecurityPolicy, validate_run_security
from .app_server_capabilities import AppServerCapabilitySet, discover_app_server_capabilities
from .profiles import PROFILES, get_profile
from .registry import RunRegistry
from .runtime import codex_environment, probe, redact, resolve_codex_command


class CodexBridge:
    """High-level Python facade over the installed Codex CLI.

    One-shot execution is backed by `codex exec`. Persistent thread/turn APIs
    are deliberately not exposed in this phase.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path | None = None,
        allowed_roots: tuple[str | Path, ...] | list[str | Path] = (),
        default_timeout_seconds: float = 300,
        default_security_policy: RunSecurityPolicy | None = None,
        app_server_capability_override: AppServerCapabilitySet | None = None,
    ) -> None:
        if state_dir is None:
            configured_state = os.environ.get("P4_CODEX_BRIDGE_STATE_DIR")
            if configured_state:
                state_dir = configured_state
            else:
                base = Path(os.environ.get("LOCALAPPDATA", Path.home())) if os.name == "nt" else Path.home() / ".local" / "state"
                state_dir = base / "p4-codex-bridge"
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.state_dir.chmod(0o700)
        self.registry = RunRegistry(self.state_dir / "runs.sqlite3")
        self.cwd_policy = CwdPolicy(tuple(Path(root) for root in allowed_roots))
        if isinstance(default_timeout_seconds, bool) or not isinstance(default_timeout_seconds, (int, float)) or not 0 < default_timeout_seconds <= 3600:
            raise ValueError("default_timeout_seconds must be in range (0, 3600]")
        self.default_timeout_seconds = float(default_timeout_seconds)
        if default_security_policy is not None and not isinstance(default_security_policy, RunSecurityPolicy):
            raise TypeError("default_security_policy must be RunSecurityPolicy")
        self.default_security_policy = default_security_policy or RunSecurityPolicy()
        self._app_server_capability_override = app_server_capability_override
        self._app_server_capabilities: AppServerCapabilitySet | None = app_server_capability_override
        self._capability_probe_cache: dict[tuple[str, ...], str] = {}
        self._turns: dict[str, Any] = {}
        self._turn_lock = threading.RLock()
        self._cleanup_stale_files()
        self.recover_exec_runs()

    def recover_exec_runs(self) -> dict[str, list[str]]:
        """Reconcile claimed exec work without replaying it or touching unowned PIDs."""
        from .scheduler import ResourceScheduler
        scheduler = ResourceScheduler(self.registry.path)
        report: dict[str, list[str]] = {"active": [], "completed_from_result": [], "lost": []}
        now = datetime.now(timezone.utc).isoformat()
        for scheduled in scheduler.list_runs():
            run_id = scheduled["bridge_run_id"]
            if scheduled["backend"] != "exec" or scheduled["status"] not in scheduler.ACTIVE:
                continue
            raw = self.registry.raw(run_id)
            if raw is None:
                scheduler.finish(run_id, RunStatus.LOST.value, finished_at=now, error="exec registry row missing during recovery")
                report["lost"].append(run_id)
                continue
            if not scheduled.get("worker_pid"):
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(scheduled["started_at"])).total_seconds()
                except (TypeError, ValueError):
                    age = 0
                if age < 30:
                    report["active"].append(run_id)
                    continue
            worker_alive = self._identity_alive(scheduled.get("worker_pid"), scheduled.get("worker_identity"))
            if worker_alive:
                report["active"].append(run_id)
                continue
            result_data = None
            result_path = Path(raw["result_path"]) if raw.get("result_path") else None
            if result_path and result_path.is_file():
                try:
                    candidate = json.loads(result_path.read_text(encoding="utf-8"))
                    if (isinstance(candidate, dict) and candidate.get("bridge_run_id") == run_id
                            and isinstance(candidate.get("ok"), bool)
                            and isinstance(candidate.get("content"), str)
                            and isinstance(candidate.get("stderr"), str)
                            and isinstance(candidate.get("duration_ms"), int)
                            and not isinstance(candidate.get("duration_ms"), bool)
                            and (candidate.get("exit_code") is None or (isinstance(candidate.get("exit_code"), int) and not isinstance(candidate.get("exit_code"), bool)))
                            and (candidate.get("error") is None or isinstance(candidate.get("error"), dict))
                            and (not candidate["ok"] or candidate.get("exit_code") == 0)):
                        result_data = candidate
                except (OSError, json.JSONDecodeError):
                    pass
            if result_data is not None:
                code = (result_data.get("error") or {}).get("code") if isinstance(result_data.get("error"), dict) else None
                terminal = (RunStatus.COMPLETED.value if result_data["ok"] else
                    RunStatus.TIMED_OUT.value if code == "CODEX_TIMEOUT" else
                    RunStatus.CANCELLED.value if code == "CODEX_CANCELLED" else
                    RunStatus.STOPPED.value if code == "CODEX_STOPPED" else RunStatus.FAILED.value)
                self.registry.update(run_id, status=terminal, exit_code=result_data.get("exit_code"),
                    last_error=redact(str((result_data.get("error") or {}).get("message", ""))) or None)
                scheduler.finish(run_id, terminal, finished_at=now, error=redact(str((result_data.get("error") or {}).get("message", ""))) or None)
                self.registry.add_run_event(run_id, terminal, {"recovered_from_result": True})
                report["completed_from_result"].append(run_id)
                continue
            child_pid, child_identity = scheduled.get("process_pid"), scheduled.get("process_identity")
            if child_pid and self._identity_alive(child_pid, child_identity) and self._identity_alive(child_pid, child_identity):
                # The controller owned this child, but its pipe/result collector is gone.
                _terminate_tree(child_pid, force=True)
            message = "exec controller disappeared; result could not be verified"
            self.registry.update(run_id, status=RunStatus.LOST.value, last_error=message)
            scheduler.finish(run_id, RunStatus.LOST.value, finished_at=now, error=message)
            self.registry.add_run_event(run_id, RunStatus.LOST.value, {"recovered": True})
            report["lost"].append(run_id)
        if report["lost"] or report["completed_from_result"]:
            from ._exec_dispatch import dispatch
            dispatch(self.registry.path)
        return report

    def _cleanup_stale_files(self) -> None:
        cutoff = time.time() - 24 * 60 * 60
        for folder in (self.state_dir / "results", self.state_dir / "temp", self.state_dir / "control"):
            if not folder.exists():
                continue
            for path in folder.iterdir():
                try:
                    if path.is_file() and path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue

    def get_version(self) -> str:
        output = probe(["--version"])
        return output.strip().splitlines()[0] if output.strip() else ""

    def _require_app_server_capability(self, feature: str) -> None:
        if self._app_server_capabilities is None:
            self._app_server_capabilities = discover_app_server_capabilities(timeout=10)
        self._app_server_capabilities.require(feature)

    def _require_exec_capability(self, operation: str, *, flag: str | None = None) -> None:
        args = ["exec", operation, "--help"] if operation in {"resume", "fork", "review"} else ["exec", "--help"]
        key = tuple(args)
        if key not in self._capability_probe_cache:
            self._capability_probe_cache[key] = probe(args)
        output = self._capability_probe_cache[key]
        supported = "Usage:" in output and (flag is None or flag in output)
        if not supported:
            requested = f"exec.{operation}" if operation in {"resume", "fork", "review"} else f"exec.{flag.lstrip('-').replace('-', '_')}"
            raise CapabilityUnavailableError(f"Codex capability {requested} is not exposed by the installed CLI")

    def get_capabilities(self) -> dict[str, Any]:
        root_help = probe(["--help"])
        exec_help = probe(["exec", "--help"])
        resume_help = probe(["exec", "resume", "--help"])
        fork_help = probe(["exec", "fork", "--help"])
        review_help = probe(["exec", "review", "--help"])
        app_help = probe(["app-server", "--help"])
        version = self.get_version()
        if self._app_server_capabilities is None:
            self._app_server_capabilities = discover_app_server_capabilities(timeout=10)
        app_caps = self._app_server_capabilities

        def capability(supported: bool, source: str, *, experimental: bool = False, notes: tuple[str, ...] = ()) -> dict[str, Any]:
            return {"status": "SUPPORTED" if supported else "NOT_SUPPORTED", "source": source, "experimental": experimental, "notes": list(notes)}

        def observed(feature: str, notes: tuple[str, ...] = ()) -> dict[str, Any]:
            return {"status": app_caps.status(feature).value, "source": app_caps.source,
                    "experimental": True, "notes": list(notes)}

        cli_source = f"installed CLI {version} --help"
        exec_available = "Usage:" in exec_help
        operation_help = {"resume": resume_help, "fork": fork_help, "review": review_help}
        exec_capabilities = {
            "available": exec_available,
            "status": "SUPPORTED" if exec_available else "NOT_SUPPORTED",
            "source": cli_source,
            "experimental": False,
            "subcommands": [name for name, help_text in operation_help.items() if "Usage:" in help_text],
            "operations": {name: capability("Usage:" in help_text, f"installed CLI: codex exec {name} --help") for name, help_text in operation_help.items()},
            "resume_supported_by_cli": "Usage:" in resume_help,
            "fork_supported_by_cli": "Usage:" in fork_help,
            "review_supported_by_cli": "Usage:" in review_help,
            "json_events": "--json" in exec_help,
            "output_schema": "--output-schema" in exec_help,
            "output_last_message": "--output-last-message" in exec_help,
            "stdin_prompt": "stdin" in exec_help.lower(),
            "sandbox": [mode.value for mode in SandboxMode if mode.value in exec_help],
            "approval_policies": [policy.value for policy in ApprovalPolicy if policy.value in root_help],
            "model": "--model" in exec_help,
            "cwd": "-C" in exec_help or "--cd" in exec_help,
            "additional_writable_roots": "--add-dir" in exec_help,
            "ignore_user_config": "--ignore-user-config" in exec_help,
        }
        exec_capabilities.update({
            "structured_output_capability": capability("--output-schema" in exec_help, cli_source),
            "last_message_capability": capability("--output-last-message" in exec_help, cli_source),
            "writable_roots_capability": capability("--add-dir" in exec_help, cli_source, notes=("CLI --add-dir is an additional writable directory; bridge still validates roots.",)),
            "reasoning_effort": capability(True, "installed model/list metadata; selected values are model-specific"),
            "reasoning_summary": capability(True, "installed app-server ConfigReadResponse schema: auto/concise/detailed/none", experimental=True),
            "verbosity": capability(True, "installed app-server ConfigReadResponse schema: low/medium/high", experimental=True),
        })
        return {
            "version": version,
            "exec": exec_capabilities,
            "app_server": {
                "available": "Usage:" in app_help,
                "status": "SUPPORTED" if "Usage:" in app_help else "NOT_SUPPORTED",
                "source": cli_source,
                "experimental": "experimental" in app_help.lower(),
                "transports": [item for item in ("stdio://", "unix://", "ws://") if item in app_help],
                "capability_snapshot": app_caps.to_dict(),
                "compatibility": {"app_server_available": "Usage:" in app_help,
                    "protocol_compatible": all(app_caps.status(feature).value == "SUPPORTED" for feature in ("app_server.thread.create", "app_server.turn.start")),
                    "missing_required_features": [feature for feature in ("app_server.thread.create", "app_server.turn.start") if app_caps.status(feature).value == "UNSUPPORTED"],
                    "limited_features": [feature for feature, status in app_caps.statuses.items() if status.value == "SUPPORTED_WITH_LIMITATIONS"],
                    "unknown_features": [feature for feature, status in app_caps.statuses.items() if status.value == "UNKNOWN"],
                    "warnings": [app_caps.error] if app_caps.error else []},
            },
            "models": {"status": "PARTIAL", "bridge_support": "IMPLEMENTED",
                       "codex_support": observed("app_server.models.list", ("Listed models do not establish account entitlement.",))},
            "permissions": {
                "status": "PARTIAL",
                "codex_support": observed("app_server.config.read"),
                "source": cli_source + " and generated app-server schema",
                "experimental": True,
                "sandbox_modes_exec": [mode.value for mode in SandboxMode if mode.value in exec_help],
                "approval_policies_exec": [policy.value for policy in ApprovalPolicy if policy.value in root_help],
                "approval_policies_app_server": [policy.value for policy in AppServerApprovalPolicy],
                "writable_roots": "--add-dir for exec; writableRoots for app-server workspaceWrite",
                "network": "sandbox_workspace_write.network_access config for exec; networkAccess for app-server sandboxPolicy; not a general MCP/tool network control",
                "notes": ["danger-full-access has no independently configurable networkAccess field.", "exec resume/fork do not expose sandbox or approval flags; they retain the session's stored policy."],
            },
            "config": {
                "status": "PARTIAL",
                "codex_support": observed("app_server.mcp.list"),
                "source": cli_source + " and app-server config/read schema",
                "experimental": True,
                "policies": {
                    "isolated": "exec --ignore-user-config; does not prove project .codex config or AGENTS are ignored",
                    "project": "native config layers resolved using child process cwd; project config may be trust-gated",
                    "explicit": "native layers plus validated session -c overrides; -c has precedence over file layers",
                    "user": "user-only layer cannot be selected by the observed exec interface",
                },
                "introspection": "app-server config/read exposes effective config and layer origins for a supplied cwd; bridge get_effective_config returns a credential-filtered subset",
            },
            "mcp": {
                "status": "PARTIAL",
                "codex_support": observed("app_server.skills.list"),
                "source": "installed app-server schema mcpServerStatus/list",
                "experimental": True,
                "session_visible": "NOT_INSPECTABLE_FROM_BRIDGE",
                "configured_child": "DISCOVERY_SUPPORTED_BY_APP_SERVER",
                "child_visible_for_exec_run": "NOT_CONFIRMED",
                "effective_for_run": "NOT_CONFIRMED",
                "per_run_control": "not exposed by the exec CLI help; app-server config is available at server/thread scope but exact tool filtering not implemented",
            },
            "skills": {
                "status": "PARTIAL",
                "source": "installed app-server schema skills/list and official Codex CLI docs",
                "experimental": True,
                "session_visible": "NOT_INSPECTABLE_FROM_BRIDGE",
                "child_visible": "NOT_CONFIRMED_FOR_EXEC",
                "effective_for_run": "NOT_CONFIRMED",
            },
            "agents": {
                "status": "UNKNOWN",
                "source": "local smoke required",
                "experimental": False,
                "session_visible": "NOT_INSPECTABLE_FROM_BRIDGE",
                "child_visible": "NOT_CONFIRMED",
                "effective_for_run": "NOT_CONFIRMED",
            },
            "other_cli_subcommands": [name for name in ("review", "login", "mcp", "resume", "agents", "features") if name in root_help],
            "phase_3": {"app_server_events": True, "streaming": True, "approvals": True, "persistent_sessions": False},
            "config_policy": {
                "isolated": "exec --ignore-user-config; project settings and instructions may still load",
                "project": "native layers for child process cwd",
                "explicit": "native layers plus a validated config allowlist supplied through -c",
                "user_only": "not independently selectable by the installed CLI",
            },
        }

    def list_models(self, *, include_hidden: bool = False, timeout_seconds: float = 30) -> list[dict[str, Any]]:
        """Fetch the installed app-server model catalog; it is not an entitlement check."""
        self._require_app_server_capability("app_server.models.list")
        process = subprocess.Popen(
            resolve_codex_command() + ["app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            shell=False,
            cwd=str(Path.cwd()),
            env=codex_environment(),
        )
        events: queue.Queue[str | None] = queue.Queue()

        def read_lines() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                events.put(line)
            events.put(None)

        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()

        def send(message: dict[str, Any]) -> None:
            assert process.stdin is not None
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()

        def response_for(request_id: int) -> dict[str, Any]:
            deadline = time.monotonic() + timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Codex app-server model discovery timed out")
                try:
                    line = events.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError("Codex app-server model discovery timed out") from exc
                if line is None:
                    raise RuntimeError("Codex app-server exited during model discovery")
                event = json.loads(line)
                if event.get("id") == request_id:
                    if "error" in event:
                        raise RuntimeError("Codex app-server rejected model discovery request")
                    return event.get("result", {})

        try:
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "p4-codex-bridge", "title": "P4 Codex Bridge", "version": __version__}}})
            response_for(1)
            send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            send({"jsonrpc": "2.0", "id": 2, "method": "model/list", "params": {"includeHidden": include_hidden}})
            models: list[dict[str, Any]] = []
            response = response_for(2)
            models.extend(response.get("data", []))
            cursor = response.get("nextCursor")
            while cursor:
                send({"jsonrpc": "2.0", "id": 3, "method": "model/list", "params": {"includeHidden": include_hidden, "cursor": cursor}})
                response = response_for(3)
                models.extend(response.get("data", []))
                cursor = response.get("nextCursor")
            return models
        finally:
            if process.stdin:
                process.stdin.close()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()

    def _app_server_request(
        self, method: str, params: dict[str, Any], *, cwd: Path,
        timeout_seconds: float = 30, config_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue one schema-verified JSON-RPC request to a short-lived local app-server."""
        from .runtime import _toml_scalar
        command = resolve_codex_command() + ["app-server"]
        for key, value in (config_overrides or {}).items():
            command.extend(["-c", f"{key}={_toml_scalar(value)}"])
        command.extend(["--listen", "stdio://"])
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", shell=False, cwd=str(cwd), env=codex_environment(),
        )
        events: queue.Queue[str | None] = queue.Queue()

        def read_lines() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                events.put(line)
            events.put(None)

        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()

        def send(message: dict[str, Any]) -> None:
            assert process.stdin is not None
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()

        def response_for(request_id: int) -> dict[str, Any]:
            deadline = time.monotonic() + timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Codex app-server {method} timed out")
                try:
                    line = events.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError(f"Codex app-server {method} timed out") from exc
                if line is None:
                    raise RuntimeError(f"Codex app-server exited during {method}")
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError(f"Codex app-server rejected {method}")
                    result = message.get("result", {})
                    return result if isinstance(result, dict) else {}

        try:
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "p4-codex-bridge", "title": "P4 Codex Bridge", "version": __version__}}})
            response_for(1)
            send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            send({"jsonrpc": "2.0", "id": 2, "method": method, "params": params})
            return response_for(2)
        finally:
            if process.stdin:
                process.stdin.close()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
            reader.join(timeout=1)

    @staticmethod
    def _normalize_policy(policy: str | ConfigPolicy, overrides: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
        try:
            selected = ConfigPolicy(policy).value
        except ValueError as exc:
            raise ValueError("config_policy must be isolated, project or explicit") from exc
        values = dict(overrides or {})
        allowed = {"model", "model_reasoning_effort", "model_reasoning_summary", "model_verbosity"}
        if any(key not in allowed for key in values):
            raise ValueError("unsupported Codex config override key")
        for key, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} override must be a non-empty string")
        if "model_reasoning_summary" in values:
            ReasoningSummary(values["model_reasoning_summary"])
        if "model_verbosity" in values:
            ModelVerbosity(values["model_verbosity"])
        if "model" in values and not re.fullmatch(r"[A-Za-z0-9._:/+-]{1,100}", values["model"]):
            raise ValueError("invalid model config override")
        if selected == "explicit" and not values:
            raise ValueError("config_overrides are required for explicit config_policy")
        if selected != "explicit" and values:
            raise ValueError("config_overrides require explicit config_policy")
        if selected == "isolated":
            raise NotImplementedError("app-server has no --ignore-user-config option; effective config cannot be probed as isolated")
        return selected, values

    def get_effective_config(
        self, *, cwd: str | Path, config_policy: str | ConfigPolicy = ConfigPolicy.PROJECT,
        config_overrides: dict[str, Any] | None = None, timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Return a secret-free whitelist of effective settings and their layer origins."""
        policy, overrides = self._normalize_policy(config_policy, config_overrides)
        self._require_app_server_capability("app_server.config.read")
        root = self.cwd_policy.resolve(cwd)
        result = self._app_server_request("config/read", {"cwd": str(root), "includeLayers": True}, cwd=root, timeout_seconds=timeout_seconds, config_overrides=overrides)
        raw_config = result.get("config", {})
        fields = ("model", "model_reasoning_effort", "model_reasoning_summary", "model_verbosity", "approval_policy", "sandbox_mode")
        values = {key: raw_config[key] for key in fields if key in raw_config and isinstance(raw_config[key], (str, int, float, bool, type(None)))}
        sources: dict[str, str] = {}
        for key, item in result.get("origins", {}).items():
            name = item.get("name", {}) if isinstance(item, dict) else {}
            if key in fields and isinstance(name, dict) and isinstance(name.get("type"), str):
                sources[str(key)] = name["type"]
        layers = []
        for item in result.get("layers") or []:
            name = item.get("name", {}) if isinstance(item, dict) else {}
            kind = name.get("type", "unknown") if isinstance(name, dict) else "unknown"
            layers.append({"source": kind, "disabled": bool(item.get("disabledReason"))})
        return {"config_policy": policy, "cwd": str(root), "values": values, "sources": sources, "layers": layers}

    def list_configured_mcps(
        self, *, cwd: str | Path, config_policy: str | ConfigPolicy = ConfigPolicy.PROJECT,
        config_overrides: dict[str, Any] | None = None, timeout_seconds: float = 30,
    ) -> list[dict[str, Any]]:
        """Discover MCP servers in a diagnostic app-server using the selected cwd/config."""
        policy, overrides = self._normalize_policy(config_policy, config_overrides)
        self._require_app_server_capability("app_server.mcp.list")
        root = self.cwd_policy.resolve(cwd)
        response = self._app_server_request(
            "mcpServerStatus/list", {"detail": "toolsAndAuthOnly", "limit": 1000},
            cwd=root, timeout_seconds=timeout_seconds, config_overrides=overrides,
        )
        rows = []
        for item in response.get("data", []):
            status = item.get("runtimeStatus")
            tool_map = item.get("tools") if isinstance(item.get("tools"), dict) else {}
            tool_names = sorted(str(name) for name in tool_map)
            enabled = False if status == "disabled" else (True if status in {"starting", "connected", "authenticationRequired"} else None)
            # The status API advertises tools but does not invoke them. Keep
            # callable unknown even when the diagnostic server is connected.
            callable_status = False if status in {"disabled", "failed", "cancelled"} else None
            raw_auth_status = item.get("authStatus")
            safe_auth_status = raw_auth_status if raw_auth_status in {"unknown", "unsupported", "Unknown", "Unsupported"} else "unknown"
            rows.append({
                "name": item.get("name"), "config_policy": policy,
                "session_visible": None, "configured": True, "enabled": enabled,
                "tools_advertised": bool(tool_names),
                "callable": callable_status, "child_visible": True,
                "child_context": "diagnostic_app_server",
                "effective_for_run": None, "auth_status": safe_auth_status,
                "runtime_status": status, "tool_count": len(tool_names), "tools": tool_names,
                "tools_error": redact(item.get("toolsError") or "") or None,
            })
        return rows

    def list_effective_skills(
        self, *, cwd: str | Path, config_policy: str | ConfigPolicy = ConfigPolicy.PROJECT,
        config_overrides: dict[str, Any] | None = None, timeout_seconds: float = 30,
    ) -> list[dict[str, Any]]:
        policy, overrides = self._normalize_policy(config_policy, config_overrides)
        self._require_app_server_capability("app_server.skills.list")
        root = self.cwd_policy.resolve(cwd)
        response = self._app_server_request("skills/list", {"cwds": [str(root)], "forceReload": True}, cwd=root, timeout_seconds=timeout_seconds, config_overrides=overrides)
        skills = []
        for entry in response.get("data", []):
            if not isinstance(entry, dict):
                continue
            for skill in entry.get("skills", []):
                if isinstance(skill, dict):
                    skills.append({
                        "name": skill.get("name"), "description": redact(skill.get("description", "")),
                        "enabled": skill.get("enabled"), "scope": skill.get("scope"),
                        "plugin_id": skill.get("pluginId"), "config_policy": policy,
                        "session_visible": None, "configured": True, "enabled": skill.get("enabled"),
                        "callable": None, "child_visible": True, "child_context": "diagnostic_app_server",
                        "effective_for_run": None,
                    })
        return skills

    def get_effective_capabilities(
        self, *, cwd: str | Path | None = None, config_policy: str | ConfigPolicy = ConfigPolicy.PROJECT,
        config_overrides: dict[str, Any] | None = None, model: str | None = None,
        permissions: CodexPermissions | None = None, include_diagnostics: bool = False,
    ) -> dict[str, Any]:
        """Return capabilities without promoting diagnostic-child evidence to run evidence.

        ``include_diagnostics`` performs short-lived app-server queries for config, MCPs,
        and skills. Those observations describe that diagnostic child only; they do not
        establish what a separate ``codex exec`` run can call.
        """
        if not isinstance(include_diagnostics, bool):
            raise ValueError("include_diagnostics must be boolean")
        report = self.get_capabilities()
        unknown = {"session_visible": None, "configured": None, "enabled": None, "callable": None, "child_visible": None, "effective_for_run": None}
        report["effective"] = {
            "mcp": {**unknown, "status": "NOT_CONFIRMED", "source": "requires a matching live run; use list_configured_mcps for diagnostic child discovery"},
            "skills": {**unknown, "status": "NOT_CONFIRMED", "source": "requires a matching live run; use list_effective_skills for diagnostic child discovery"},
            "agents": {**unknown, "status": "NOT_CONFIRMED", "source": "AGENTS.md consumption is not reported by Codex exec"},
            "config": {**unknown, "status": "NOT_CONFIRMED", "config_policy": str(config_policy), "source": "use get_effective_config; isolated policy cannot be fully probed via app-server"},
            "model": {**unknown, "status": "REQUESTED" if model else "FROM_CONFIG_OR_DEFAULT", "requested_model": model},
            "sandbox": {**unknown, "status": "REQUESTED" if permissions else "PROFILE_OR_DEFAULT", "requested_sandbox": SandboxMode(permissions.sandbox).value if permissions else None},
            "approvals": {**unknown, "status": "REQUESTED" if permissions else "PROFILE_OR_DEFAULT", "requested_approval_policy": AppServerApprovalPolicy(permissions.approval_policy).value if permissions else None},
        }
        if cwd is not None:
            root = self.cwd_policy.resolve(cwd)
            report["effective"]["cwd"] = str(root)
            if include_diagnostics:
                try:
                    selected_policy = ConfigPolicy(config_policy)
                except ValueError as exc:
                    raise ValueError("config_policy must be isolated, project or explicit") from exc
                if selected_policy == ConfigPolicy.ISOLATED:
                    unavailable = {"status": "NOT_SUPPORTED", "scope": "diagnostic_app_server", "reason": "app-server has no equivalent of exec --ignore-user-config"}
                    report["effective"]["mcp"]["diagnostic_child"] = dict(unavailable)
                    report["effective"]["skills"]["diagnostic_child"] = dict(unavailable)
                    report["effective"]["config"]["diagnostic_child"] = dict(unavailable)
                else:
                    diagnostic: dict[str, Any] = {"scope": "short_lived_app_server", "config_policy": selected_policy.value}
                    for key, operation in (
                        ("config", lambda: self.get_effective_config(cwd=root, config_policy=selected_policy, config_overrides=config_overrides)),
                        ("mcp", lambda: self.list_configured_mcps(cwd=root, config_policy=selected_policy, config_overrides=config_overrides)),
                        ("skills", lambda: self.list_effective_skills(cwd=root, config_policy=selected_policy, config_overrides=config_overrides)),
                    ):
                        try:
                            diagnostic[key] = {"status": "CONFIRMED", "data": operation()}
                        except Exception as exc:
                            diagnostic[key] = {"status": "ERROR", "error_class": type(exc).__name__}
                    report["effective"]["config"]["diagnostic_child"] = diagnostic["config"]
                    report["effective"]["mcp"]["diagnostic_child"] = diagnostic["mcp"]
                    report["effective"]["skills"]["diagnostic_child"] = diagnostic["skills"]
                report["diagnostic_child"] = {"kind": "app-server", "scope": "short_lived", "results": {
                    key: report["effective"][key]["diagnostic_child"] for key in ("config", "mcp", "skills")}}
        elif include_diagnostics:
            raise ValueError("cwd is required when include_diagnostics=True")
        return report

    def start_turn(
        self, prompt: str, *, cwd: str | Path, profile: str = "analysis", model: str | None = None,
        permissions: CodexPermissions | None = None, reasoning_effort: str | None = None,
        app_server_approval_policy: AppServerApprovalPolicy | str | None = None,
        output_schema: dict[str, Any] | None = None, approval_timeout_seconds: float = 300,
        approval_timeout_policy: str = "reject",
        approval_handling_policy: ApprovalHandlingPolicy = ApprovalHandlingPolicy.MANUAL,
        queue_size: int = 256, metadata: dict[str, Any] | None = None, announce_run: bool = False,
        security_policy: RunSecurityPolicy | None = None,
    ):
        """Start a live app-server turn. Closing its CodexTurn closes only this managed server."""
        from .app_server import start_turn
        self._require_app_server_capability("app_server.thread.create")
        self._require_app_server_capability("app_server.turn.start")
        resolved_cwd = self.cwd_policy.resolve(cwd)
        security_policy = security_policy or self.default_security_policy
        security_result = validate_run_security(security_policy, backend="app-server", config_policy="project", cwd=resolved_cwd)
        selected_permissions = permissions or get_profile(profile).permissions
        writable_roots = self.cwd_policy.resolve_writable_roots(selected_permissions.writable_roots, cwd=resolved_cwd)
        approval_policy = app_server_approval_policy or selected_permissions.approval_policy.value
        from .registry import _clean_metadata
        if not isinstance(announce_run, bool): raise ValueError("announce_run must be boolean")
        metadata = _clean_metadata(metadata or {})
        bridge_run_id = "br_" + uuid.uuid4().hex[:12]
        self.registry.create(bridge_run_id, backend="app-server", cwd=str(resolved_cwd), model=model, profile=profile,
                             result_path="", agent_metadata=metadata, permissions=selected_permissions.to_dict() if hasattr(selected_permissions, "to_dict") else {"sandbox": selected_permissions.sandbox.value, "approval_policy": selected_permissions.approval_policy.value, "writable_roots": [str(x) for x in selected_permissions.writable_roots]}, config_policy="project", security_snapshot={"project_trust": security_policy.project_trust.value, "policy_id": security_result.policy_id, "risk_acknowledged": security_policy.explicit_risk_acknowledgement, "mcp_isolation_required": security_policy.require_mcp_isolation, "decision": security_result.decision.value})
        try:
            turn = start_turn(
            prompt, cwd=resolved_cwd, model=model, sandbox=selected_permissions.sandbox,
            approval_policy=approval_policy, reasoning_effort=reasoning_effort,
            writable_roots=writable_roots, network_access=selected_permissions.network_access,
            output_schema=output_schema, approval_timeout_seconds=approval_timeout_seconds,
            approval_timeout_policy=approval_timeout_policy,
                approval_handling_policy=approval_handling_policy, queue_size=queue_size, registry=self.registry,
            )
        except Exception as exc:
            self.registry.update(bridge_run_id, status=RunStatus.FAILED.value, last_error=redact(str(exc)))
            raise
        turn.bridge_run_id = bridge_run_id
        turn.agent_metadata = metadata
        turn.connection.bridge_run_id = bridge_run_id
        turn.connection.announce_run = announce_run
        server_id = "as_" + uuid.uuid4().hex[:12]
        state_to_status = {"COMPLETED": RunStatus.COMPLETED.value, "FAILED": RunStatus.FAILED.value, "INTERRUPTED": RunStatus.INTERRUPTED.value, "WAITING_APPROVAL": RunStatus.WAITING_APPROVAL.value}
        self.registry.update(bridge_run_id, server_id=server_id, pid=turn.connection.process.pid,
                             pid_identity=_identity(turn.connection.process.pid), thread_id=turn.thread_id, turn_id=turn.turn_id,
                             status=state_to_status.get(turn.status, RunStatus.RUNNING.value))
        if announce_run: logging.getLogger("p4_codex_bridge.announce").info(self.format_run_announcement(bridge_run_id))
        self._prune_turn_handles()
        with self._turn_lock:
            self._turns[turn.turn_id] = turn
        return turn

    def _prune_turn_handles(self) -> None:
        with self._turn_lock:
            terminal = [key for key, turn in self._turns.items() if turn.status in {"COMPLETED", "FAILED", "INTERRUPTED", "STOPPED"}]
            old = [self._turns.pop(key) for key in terminal]
        for turn in old:
            turn.close()

    def stream_events(self, prompt: str, **options: Any):
        turn_timeout = options.pop("turn_timeout_seconds", self.default_timeout_seconds)
        turn = self.start_turn(prompt, **options)
        completed = False
        try:
            for event in turn.events(timeout=turn_timeout):
                if event.type in {"TurnCompleted", "TurnFailed", "TurnInterrupted"}:
                    completed = True
                yield event
                if completed:
                    break
        finally:
            if completed:
                with self._turn_lock:
                    self._turns.pop(turn.turn_id, None)
                turn.close()
            else:
                turn.detach_event_consumer()

    def get_turn_handle(self, turn_id: str):
        """Return a live handle after a stream consumer disconnects, if it is still owned here."""
        with self._turn_lock:
            try:
                return self._turns[turn_id]
            except KeyError as exc:
                raise KeyError(turn_id) from exc

    async def astream_events(self, prompt: str, **options: Any):
        """Async iterator backed by the same synchronous app-server reader and queue."""
        iterator = self.stream_events(prompt, **options)
        sentinel = object()
        def next_or_sentinel():
            try:
                return next(iterator)
            except StopIteration:
                return sentinel
        try:
            while True:
                event = await asyncio.to_thread(next_or_sentinel)
                if event is sentinel:
                    return
                yield event
        finally:
            close = getattr(iterator, "close", None)
            if close:
                close()

    def stream_all_events(
        self, *, thread_id: str | None = None, turn_id: str | None = None,
        timeout: float = 300, queue_size: int = 256,
    ):
        """Observe events from all currently bridge-owned live turns in this process."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 3600:
            raise ValueError("timeout must be in range (0, 3600]")
        if isinstance(queue_size, bool) or not isinstance(queue_size, int) or not 1 <= queue_size <= 65536:
            raise ValueError("queue_size must be an integer from 1 to 65536")
        subscriptions: dict[int, tuple[Any, Any]] = {}
        seen_connections: set[int] = set()
        started = time.monotonic()
        try:
            while time.monotonic() - started < timeout:
                with self._turn_lock:
                    turns = tuple(self._turns.values())
                live_connections = {id(turn.connection) for turn in turns if turn.status in {"STARTING", "RUNNING", "WAITING_APPROVAL", "STOPPING"}}
                for key in live_connections - subscriptions.keys():
                    turn = next(turn for turn in turns if id(turn.connection) == key)
                    subscriptions[key] = (turn.connection, turn.connection.subscribe(thread_id=thread_id, turn_id=turn_id, queue_size=queue_size))
                    seen_connections.add(key)
                for key, (connection, subscription) in tuple(subscriptions.items()):
                    while True:
                        try:
                            event = subscription.queue.get_nowait()
                        except queue.Empty:
                            break
                        if event is None:
                            continue
                        if isinstance(event, BaseException):
                            raise event
                        yield event
                    if connection.state not in {"STARTING", "RUNNING", "WAITING_APPROVAL", "STOPPING"} and subscription.queue.empty():
                        connection.unsubscribe(subscription)
                        subscriptions.pop(key, None)
                if seen_connections and not subscriptions and not live_connections:
                    return
                time.sleep(0.01)
            raise TimeoutError("server-wide event stream timed out")
        finally:
            for connection, subscription in subscriptions.values():
                connection.unsubscribe(subscription)

    async def astream_all_events(self, **options: Any):
        iterator = self.stream_all_events(**options)
        sentinel = object()
        def next_or_sentinel():
            try:
                return next(iterator)
            except StopIteration:
                return sentinel
        try:
            while True:
                event = await asyncio.to_thread(next_or_sentinel)
                if event is sentinel:
                    return
                yield event
        finally:
            close = getattr(iterator, "close", None)
            if close:
                close()

    def get_turn_status(self, turn_id: str) -> str:
        with self._turn_lock:
            turn = self._turns.get(turn_id)
        if turn:
            return turn.status
        for row in self.registry.list_turn_states():
            if row["turn_id"] == turn_id:
                return row["status"]
        raise KeyError(turn_id)

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        return self.registry.list_approvals(pending_only=True) + self.registry.list_runtime_approvals(pending_only=True)

    def approve(self, approval_id: str) -> None:
        self._resolve_approval(approval_id, approve=True)

    def reject(self, approval_id: str) -> None:
        self._resolve_approval(approval_id, approve=False)

    def _resolve_approval(self, approval_id: str, *, approve: bool) -> None:
        try:
            self.registry.submit_runtime_approval_decision(approval_id, "accept" if approve else "decline")
            return
        except KeyError:
            pass
        try:
            self.registry.submit_approval_decision(approval_id, "accept" if approve else "decline")
        except KeyError as exc:
            raise ApprovalError(str(exc)) from exc

    def get_event_metrics(self) -> dict[str, int]:
        self._prune_turn_handles()
        with self._turn_lock:
            turns = tuple(self._turns.values())
        return {
            "active_streams": sum(1 for turn in turns if turn.status in {"STARTING", "RUNNING", "WAITING_APPROVAL"}),
            "pending_approvals": sum(1 for turn in turns if turn.pending_approval),
            "events_received": sum(turn.connection.events_received for turn in turns),
            "events_dropped": sum(turn.connection.events_dropped for turn in turns),
            "turns_waiting_approval": sum(1 for turn in turns if turn.status == "WAITING_APPROVAL"),
        }

    def get_events(self, *, thread_id: str | None = None, turn_id: str | None = None, after_sequence: int = 0) -> list[dict[str, Any]]:
        return self.registry.list_turn_events(thread_id=thread_id, turn_id=turn_id, after_sequence=after_sequence)

    def start(
        self,
        prompt: str,
        *,
        cwd: str | Path,
        profile: str = "analysis",
        model: str | None = None,
        timeout_seconds: float | None = None,
        permissions: CodexPermissions | None = None,
        reasoning_effort: str | None = None,
        reasoning_summary: ReasoningSummary | str | None = None,
        verbosity: ModelVerbosity | str | None = None,
        output_schema: dict[str, Any] | None = None,
        capture_last_message: bool = False,
        include_raw_output: bool = False,
        config_policy: str | None = None,
        config_overrides: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        announce_run: bool = False,
        access_mode: str = "READ",
        resource_priority: int = 0,
        security_policy: RunSecurityPolicy | None = None,
    ) -> BridgeRun:
        """Submit an asynchronous exec job through the shared persistent resource queue."""
        request = self._validate_request(
            prompt, cwd=cwd, profile=profile, model=model, timeout_seconds=timeout_seconds,
            permissions=permissions, reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary, verbosity=verbosity, output_schema=output_schema,
            capture_last_message=capture_last_message, include_raw_output=include_raw_output,
            config_policy=config_policy, config_overrides=config_overrides,
            security_policy=security_policy,
        )
        if not isinstance(announce_run, bool): raise ValueError("announce_run must be boolean")
        request["operation"] = "run"
        request["announce_run"] = announce_run
        from .scheduler import ResourceScheduler
        from .registry import _clean_metadata
        safe_metadata = _clean_metadata(metadata or {})
        effective_permissions = permissions or get_profile(profile).permissions
        run_id = "br_" + uuid.uuid4().hex[:12]
        result_path = self.state_dir / "results" / f"{run_id}.json"
        now = datetime.now(timezone.utc).isoformat()
        permissions_data = {"sandbox": effective_permissions.sandbox.value,
            "approval_policy": effective_permissions.approval_policy.value,
            "network_access": effective_permissions.network_access,
            "writable_roots": [str(x) for x in effective_permissions.writable_roots]}

        def insert_registry_row(db, bridge_run_id: str) -> None:
            db.execute("INSERT INTO runs(bridge_run_id,backend,cwd,model,profile,started_at,status,result_path,agent_metadata_json,permissions_json,config_policy,security_snapshot_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (bridge_run_id, "exec", request["cwd"], model, profile, now, RunStatus.QUEUED.value,
                 str(result_path), json.dumps(safe_metadata, ensure_ascii=False),
                 json.dumps(permissions_data, ensure_ascii=False), request.get("config_policy"),
                 json.dumps(request.get("security_snapshot", {}), ensure_ascii=False)))

        scheduler = ResourceScheduler(self.registry.path)
        scheduler.submit(turn_id=run_id, thread_id=run_id, backend="exec", profile=profile,
            workspace=request["cwd"], prompt=prompt, payload_data=request,
            access_mode=access_mode, priority=resource_priority, metadata=safe_metadata,
            bridge_run_id=run_id, submitted_at=now, transaction_hook=insert_registry_row)
        self.registry.add_run_event(run_id, "SUBMITTED", {"backend": "exec", "workspace": request["cwd"], "access_mode": access_mode.upper()})
        self.registry.add_run_event(run_id, "QUEUED", {"resource_priority": resource_priority})
        from ._exec_dispatch import dispatch
        dispatch(self.registry.path)
        record = self.get_run(run_id)
        if announce_run:
            logging.getLogger("p4_codex_bridge.announce").info(self.format_run_announcement(run_id))
        return record

    def _start_direct(
        self,
        prompt: str,
        *,
        cwd: str | Path,
        profile: str = "analysis",
        model: str | None = None,
        timeout_seconds: float | None = None,
        permissions: CodexPermissions | None = None,
        reasoning_effort: str | None = None,
        reasoning_summary: ReasoningSummary | str | None = None,
        verbosity: ModelVerbosity | str | None = None,
        output_schema: dict[str, Any] | None = None,
        capture_last_message: bool = False,
        include_raw_output: bool = False,
        config_policy: str | None = None,
        config_overrides: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        announce_run: bool = False,
        security_policy: RunSecurityPolicy | None = None,
    ) -> BridgeRun:
        if output_schema is not None:
            self._require_exec_capability("run", flag="--output-schema")
        if capture_last_message:
            self._require_exec_capability("run", flag="--output-last-message")
        request = self._validate_request(
            prompt, cwd=cwd, profile=profile, model=model,
            timeout_seconds=timeout_seconds, permissions=permissions,
            reasoning_effort=reasoning_effort, reasoning_summary=reasoning_summary,
            verbosity=verbosity, output_schema=output_schema,
            capture_last_message=capture_last_message, include_raw_output=include_raw_output,
            config_policy=config_policy, config_overrides=config_overrides,
            security_policy=security_policy,
        )
        request["operation"] = "run"
        if not isinstance(announce_run, bool): raise ValueError("announce_run must be boolean")
        request["announce_run"] = announce_run
        record = self._launch_request(request, profile=profile, metadata=metadata, permissions=permissions or get_profile(profile).permissions, config_policy=request.get("config_policy"))
        if announce_run: logging.getLogger("p4_codex_bridge.announce").info(self.format_run_announcement(record.bridge_run_id))
        return record

    def _launch_request(self, request: dict[str, Any], *, profile: str, metadata: dict[str, Any] | None = None,
                        permissions: CodexPermissions | None = None, config_policy: str | None = None) -> BridgeRun:
        from .registry import _clean_metadata
        metadata = _clean_metadata(metadata or {})
        run_id = "br_" + uuid.uuid4().hex[:12]
        result_path = self.state_dir / "results" / f"{run_id}.json"
        stop_path = self.state_dir / "control" / f"{run_id}.stop"
        worker_request = {**request, "agent_metadata": metadata, "state_dir": str(self.state_dir), "stop_path": str(stop_path)}
        payload = json.dumps(worker_request, ensure_ascii=False)
        if len(payload.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("run request exceeds the 2 MiB limit")
        self.registry.create(
            run_id,
            backend="codex-exec" if request.get("operation", "run") == "run" else f"codex-exec-{request['operation']}",
            cwd=request["cwd"],
            model=request.get("model"),
            profile=profile,
            result_path=str(result_path),
            agent_metadata=metadata,
            permissions={"sandbox": permissions.sandbox.value, "approval_policy": permissions.approval_policy.value,
                         "network_access": permissions.network_access, "writable_roots": [str(x) for x in permissions.writable_roots]} if permissions else None,
            config_policy=config_policy,
            security_snapshot=request.get("security_snapshot"),
        )
        command = [sys.executable, "-m", "p4_codex_bridge._worker", "--db", str(self.registry.path), "--run-id", run_id]
        worker_env = codex_environment()
        package_root = str(Path(__file__).resolve().parent.parent)
        worker_env["PYTHONPATH"] = os.pathsep.join(filter(None, (package_root, worker_env.get("PYTHONPATH", ""))))
        kwargs: dict[str, Any] = {
            "args": command,
            "cwd": package_root,
            "env": worker_env,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.DEVNULL,
            "stderr": None if request.get("announce_run") else subprocess.DEVNULL,
            "shell": False,
            "text": True,
            "encoding": "utf-8",
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startup
        else:
            kwargs["start_new_session"] = True
        try:
            worker = subprocess.Popen(**kwargs)
            assert worker.stdin is not None
            worker.stdin.write(payload)
            worker.stdin.close()
            self.registry.update(run_id, worker_pid=worker.pid, worker_identity=_identity(worker.pid))
            if os.name == "nt":
                # This run is intentionally detached; close the local process handle
                # so Python does not warn that Popen is being collected while active.
                worker._handle.Close()
                worker.returncode = 0
        except (OSError, BrokenPipeError):
            self.registry.update(run_id, status=RunStatus.FAILED.value, last_error="Bridge worker could not be started")
        return self.get_run(run_id)  # type: ignore[return-value]

    def _collect_result(self, record: BridgeRun, timeout_seconds: float | None) -> RunResult:
        run_id = record.bridge_run_id
        deadline = time.monotonic() + float(timeout_seconds or self.default_timeout_seconds) + 30
        while True:
            record = self.get_run(run_id)
            if record.status not in {RunStatus.STARTING, RunStatus.RUNNING}:
                break
            if time.monotonic() >= deadline:
                self.kill(run_id)
                return RunResult(False, run_id, None, "", "", error={"code": "BRIDGE_WAIT_TIMEOUT", "message": "Bridge worker did not report a terminal state"})
            time.sleep(0.05)
        self._wait_worker_exit(run_id, timeout=5)
        result_path = self.state_dir / "results" / f"{run_id}.json"
        if result_path.is_file():
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
            finally:
                result_path.unlink(missing_ok=True)
            return RunResult(**data)
        return RunResult(
            False, run_id, record.exit_code, "", "",
            error={"code": "BRIDGE_RESULT_MISSING", "message": record.last_error or "No result was written"},
        )

    def run(
        self,
        prompt: str,
        *,
        cwd: str | Path,
        profile: str = "analysis",
        model: str | None = None,
        timeout_seconds: float | None = None,
        permissions: CodexPermissions | None = None,
        reasoning_effort: str | None = None,
        reasoning_summary: ReasoningSummary | str | None = None,
        verbosity: ModelVerbosity | str | None = None,
        output_schema: dict[str, Any] | None = None,
        capture_last_message: bool = False,
        include_raw_output: bool = False,
        config_policy: str | None = None,
        config_overrides: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        announce_run: bool = False,
        security_policy: RunSecurityPolicy | None = None,
    ) -> RunResult:
        """Run one direct exec job and wait for its collected result."""
        timeout = timeout_seconds
        announce = announce_run
        options = {
            "cwd": cwd, "profile": profile, "model": model,
            "timeout_seconds": timeout_seconds, "permissions": permissions,
            "reasoning_effort": reasoning_effort, "reasoning_summary": reasoning_summary,
            "verbosity": verbosity, "output_schema": output_schema,
            "capture_last_message": capture_last_message, "include_raw_output": include_raw_output,
            "config_policy": config_policy, "config_overrides": config_overrides,
            "metadata": metadata, "security_policy": security_policy,
        }
        if output_schema is not None:
            self._require_exec_capability("run", flag="--output-schema")
        if capture_last_message:
            self._require_exec_capability("run", flag="--output-last-message")
        record = self._start_direct(prompt, announce_run=False, **options)
        if announce: logging.getLogger("p4_codex_bridge.announce").info(self.format_run_announcement(record.bridge_run_id))
        result = self._collect_result(record, timeout)
        if announce:
            elapsed = time.strftime("%H:%M:%S", time.gmtime(result.duration_ms / 1000))
            state = "SUCCESS" if result.ok else "FAILED"
            logging.getLogger("p4_codex_bridge.announce").info("[P4-Codex] %s %s | %s | %s", "Completed" if result.ok else "Failed", record.bridge_run_id, state, elapsed)
        return result

    def _validated_advanced_request(
        self, operation: str, prompt: str, *, cwd: str | Path, session_id: str | None = None,
        model: str | None = None, timeout_seconds: float | None = None,
        config_policy: str | ConfigPolicy = ConfigPolicy.PROJECT,
        config_overrides: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None, capture_last_message: bool = False,
        include_raw_output: bool = False, reasoning_effort: str | None = None,
        reasoning_summary: ReasoningSummary | str | None = None,
        verbosity: ModelVerbosity | str | None = None,
        confirm_inherited_permissions: bool = False,
        review_uncommitted: bool = False, review_base: str | None = None,
        review_commit: str | None = None, review_title: str | None = None,
        security_policy: RunSecurityPolicy | None = None,
    ) -> dict[str, Any]:
        if operation not in {"resume", "fork", "review"}:
            raise ValueError("unsupported advanced Codex operation")
        if operation in {"resume", "fork"}:
            if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 255 or session_id.startswith("-") or any(ord(ch) < 32 for ch in session_id):
                raise ValueError("session_id must be a UUID or safe Codex thread name")
            if not confirm_inherited_permissions:
                raise ValueError("confirm_inherited_permissions=True is required because exec resume/fork restore session policy")
        if operation in {"resume", "fork"} and (not isinstance(prompt, str) or not prompt.strip()):
            raise ValueError("prompt is required for exec resume/fork")
        if operation == "review" and (not isinstance(prompt, str) or len(prompt) > 100_000):
            raise ValueError("review instructions must be a string under 100000 characters")
        targets = int(bool(review_uncommitted)) + int(review_base is not None) + int(review_commit is not None)
        if operation == "review" and targets != 1:
            raise ValueError("review requires exactly one target: uncommitted, base or commit")
        if review_base is not None and (not isinstance(review_base, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", review_base) or review_base.startswith("-")):
            raise ValueError("invalid review base")
        if review_commit is not None and (not isinstance(review_commit, str) or not re.fullmatch(r"[A-Fa-f0-9]{7,64}", review_commit)):
            raise ValueError("review commit must be a 7-64 character hexadecimal object id")
        if review_title is not None and (not isinstance(review_title, str) or not review_title.strip() or len(review_title) > 300):
            raise ValueError("review title must be a non-empty string under 300 characters")
        request = self._validate_request(
            prompt or "codex review", cwd=cwd, profile="analysis", model=model,
            timeout_seconds=timeout_seconds, permissions=CodexPermissions(),
            reasoning_effort=reasoning_effort, reasoning_summary=reasoning_summary,
            verbosity=verbosity, output_schema=output_schema,
            capture_last_message=capture_last_message, include_raw_output=include_raw_output,
            config_policy=config_policy, config_overrides=config_overrides,
            security_policy=security_policy,
        )
        if operation == "review":
            request["prompt"] = prompt
        request.update({
            "operation": operation,
            "session_id": session_id,
            "review_uncommitted": review_uncommitted,
            "review_base": review_base,
            "review_commit": review_commit,
            "review_title": review_title,
            "permissions_inherited_from_session": operation in {"resume", "fork"},
        })
        return request

    def _run_advanced(self, request: dict[str, Any]) -> RunResult:
        self._require_exec_capability(request["operation"])
        if request.get("output_schema") is not None:
            self._require_exec_capability("run", flag="--output-schema")
        if request.get("capture_last_message"):
            self._require_exec_capability("run", flag="--output-last-message")
        record = self._launch_request(request, profile="analysis")
        return self._collect_result(record, request["timeout_seconds"])

    def resume(
        self, session_id: str, prompt: str, *, cwd: str | Path, model: str | None = None,
        timeout_seconds: float | None = None, config_policy: str | ConfigPolicy = ConfigPolicy.PROJECT,
        config_overrides: dict[str, Any] | None = None, output_schema: dict[str, Any] | None = None,
        capture_last_message: bool = False, include_raw_output: bool = False,
        reasoning_effort: str | None = None, reasoning_summary: ReasoningSummary | str | None = None,
        verbosity: ModelVerbosity | str | None = None, confirm_inherited_permissions: bool = False,
        security_policy: RunSecurityPolicy | None = None,
    ) -> RunResult:
        """Run `codex exec resume`; this is not `app-server thread/resume`."""
        request = self._validated_advanced_request(
            "resume", prompt, cwd=cwd, session_id=session_id, model=model,
            timeout_seconds=timeout_seconds, config_policy=config_policy,
            config_overrides=config_overrides, output_schema=output_schema,
            capture_last_message=capture_last_message, include_raw_output=include_raw_output,
            reasoning_effort=reasoning_effort, reasoning_summary=reasoning_summary,
            verbosity=verbosity, confirm_inherited_permissions=confirm_inherited_permissions,
            security_policy=security_policy,
        )
        return self._run_advanced(request)

    def fork(
        self, session_id: str, prompt: str, *, cwd: str | Path, model: str | None = None,
        timeout_seconds: float | None = None, config_policy: str | ConfigPolicy = ConfigPolicy.PROJECT,
        config_overrides: dict[str, Any] | None = None, output_schema: dict[str, Any] | None = None,
        capture_last_message: bool = False, include_raw_output: bool = False,
        reasoning_effort: str | None = None, reasoning_summary: ReasoningSummary | str | None = None,
        verbosity: ModelVerbosity | str | None = None, confirm_inherited_permissions: bool = False,
        security_policy: RunSecurityPolicy | None = None,
    ) -> RunResult:
        """Run `codex exec fork` and return the fork thread ID when emitted."""
        request = self._validated_advanced_request(
            "fork", prompt, cwd=cwd, session_id=session_id, model=model,
            timeout_seconds=timeout_seconds, config_policy=config_policy,
            config_overrides=config_overrides, output_schema=output_schema,
            capture_last_message=capture_last_message, include_raw_output=include_raw_output,
            reasoning_effort=reasoning_effort, reasoning_summary=reasoning_summary,
            verbosity=verbosity, confirm_inherited_permissions=confirm_inherited_permissions,
            security_policy=security_policy,
        )
        return self._run_advanced(request)

    def review(
        self, *, cwd: str | Path, instructions: str = "", uncommitted: bool = False,
        base: str | None = None, commit: str | None = None, title: str | None = None,
        model: str | None = None, timeout_seconds: float | None = None,
        config_policy: str | ConfigPolicy = ConfigPolicy.PROJECT,
        config_overrides: dict[str, Any] | None = None, output_schema: dict[str, Any] | None = None,
        capture_last_message: bool = False, include_raw_output: bool = False,
        reasoning_effort: str | None = None, reasoning_summary: ReasoningSummary | str | None = None,
        verbosity: ModelVerbosity | str | None = None,
        security_policy: RunSecurityPolicy | None = None,
    ) -> RunResult:
        """Run the installed `codex exec review` against one supported repository target."""
        request = self._validated_advanced_request(
            "review", instructions, cwd=cwd, model=model, timeout_seconds=timeout_seconds,
            config_policy=config_policy, config_overrides=config_overrides,
            output_schema=output_schema, capture_last_message=capture_last_message,
            include_raw_output=include_raw_output, reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary, verbosity=verbosity,
            review_uncommitted=uncommitted, review_base=base, review_commit=commit,
            review_title=title,
            security_policy=security_policy,
        )
        return self._run_advanced(request)

    def get_run(self, run_id: str) -> BridgeRun:
        record = self.registry.get(run_id)
        if record is None:
            raise KeyError(run_id)
        if record.status in {RunStatus.STARTING, RunStatus.RUNNING}:
            raw = self.registry.raw(run_id)
            if raw and raw.get("worker_pid"):
                if not self._identity_alive(raw["worker_pid"], raw["worker_identity"]):
                    time.sleep(0.05)
                    refreshed = self.registry.get(run_id)
                    if refreshed and refreshed.status in {RunStatus.STARTING, RunStatus.RUNNING}:
                        self.registry.update(run_id, status=RunStatus.ORPHANED.value, last_error="Managed worker exited without persisting a terminal status")
                        record = self.registry.get(run_id)  # type: ignore[assignment]
                    else:
                        record = refreshed or record
        return record

    def list_runs(self, *, active: bool | None = None, task: str | None = None, agent: str | None = None,
                  backend: str | None = None, status: str | None = None):
        if active is not None or task or agent or backend or status:
            return self.registry.discover(active=bool(active), task=task, agent=agent, backend=backend, status=status)
        runs = self.registry.list()
        return [self.get_run(run.bridge_run_id) for run in runs]

    def discover_runs(self, *, active: bool = False, task: str | None = None, agent: str | None = None,
                      backend: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        return self.registry.discover(active=active, task=task, agent=agent, backend=backend, status=status)

    def format_run_announcement(self, run_id: str) -> str:
        snapshot = self.inspect(run_id)
        metadata = snapshot.get("agent_metadata", {})
        lines = [f"[P4-Codex] Started {snapshot['bridge_run_id']}"]
        for label, key in (("Agent", "agent_name"), ("Task", "task_key")):
            if metadata.get(key): lines.append(f"[P4-Codex] {label}: {redact(str(metadata[key]))}")
        lines.extend([f"[P4-Codex] Backend: {snapshot.get('backend')}"])
        if snapshot.get("thread_id"): lines.append(f"[P4-Codex] Thread: {snapshot['thread_id']}")
        if snapshot.get("turn_id"): lines.append(f"[P4-Codex] Turn: {snapshot['turn_id']}")
        if snapshot.get("pid"): lines.append(f"[P4-Codex] PID: {snapshot['pid']}")
        lines.append(f"[P4-Codex] Watch: p4-codex watch {snapshot['bridge_run_id']} --follow")
        return "\n".join(lines)

    def resolve_run_reference(self, reference: str) -> dict[str, Any]:
        return self.registry.resolve_reference(reference)

    def inspect(self, reference: str) -> dict[str, Any]:
        return self.registry.inspect(reference)

    def watch(self, reference: str | None = None, *, task: str | None = None, agent: str | None = None,
              follow: bool = False, no_deltas: bool = False, tools: bool = True,
              approvals: bool = True, since: str | int | None = None, poll_seconds: float = 0.25):
        """Read-only watcher over persisted run events; it never controls a Codex turn."""
        if (reference is None) == (task is None and agent is None):
            raise ValueError("provide exactly one run reference or a task/agent selector")
        if reference is None and task is not None and agent is not None:
            raise ValueError("select by task or agent, not both")
        if reference is None:
            candidates = self.discover_runs(active=True, task=task, agent=agent)
            if len(candidates) != 1:
                choices = ", ".join(str(x.get("bridge_run_id")) for x in candidates) or "none"
                raise ValueError(f"selector matched {len(candidates)} active runs; choose one explicitly ({choices})")
            reference = str(candidates[0]["bridge_run_id"])
        run = self.resolve_run_reference(reference)["run"]
        after = int(since) if isinstance(since, int) or (isinstance(since, str) and since.isdigit()) else 0
        timestamp_since = since if isinstance(since, str) and not since.isdigit() else None
        last_status = None
        replay_warning_sent = False
        while True:
            for event in self.registry.events_for(run, after_sequence=after):
                seq = int(event.get("persistence_sequence", 0)); after = max(after, seq)
                if timestamp_since and event.get("timestamp", "") < timestamp_since: continue
                event_type = event.get("type") or event.get("event_type")
                if event_type == "AgentMessageDelta" and no_deltas: continue
                if str(event_type).startswith("Tool") and not tools: continue
                if "Approval" in str(event_type) and not approvals: continue
                yield event
            snapshot = self.inspect(str(run.get("bridge_run_id")))
            if snapshot.get("recovered") and not snapshot.get("event_replay_complete") and not replay_warning_sent:
                replay_warning_sent = True
                yield {"type": "ReplayWarning", "bridge_run_id": run.get("bridge_run_id"),
                       "message": "Only persisted lifecycle events are replayed; remote message deltas are unavailable.",
                       "timestamp": snapshot.get("started_at")}
            status = str(snapshot.get("status", "UNKNOWN")).upper()
            if status != last_status:
                last_status = status
                yield {"type": "RunStatus", "bridge_run_id": run.get("bridge_run_id"), "status": status, "timestamp": snapshot.get("started_at")}
            if not follow or status not in {"STARTING", "RUNNING", "WAITING_APPROVAL", "QUEUED"}: return
            time.sleep(max(0.05, min(float(poll_seconds), 5.0)))

    async def awatch(self, *args: Any, **kwargs: Any):
        iterator = self.watch(*args, **kwargs)
        sentinel = object()
        def next_or_sentinel():
            try: return next(iterator)
            except StopIteration: return sentinel
        try:
            while True:
                event = await asyncio.to_thread(next_or_sentinel)
                if event is sentinel: return
                yield event
        finally:
            iterator.close()

    def status(self, run_id: str) -> BridgeRun | dict[str, Any]:
        try:
            return self.get_run(run_id)
        except KeyError:
            for state in self.registry.list_turn_states():
                if state["turn_id"] == run_id:
                    return state
            raise

    def list_managed(self) -> list[Any]:
        """Return a CLI/observability view of exec jobs and app-server turns."""
        active_exec = [run.to_dict() for run in self.list_runs() if run.status in {RunStatus.STARTING, RunStatus.RUNNING}]
        active_turns = [row for row in self.registry.list_turn_states() if row["status"] in {"STARTING", "RUNNING", "WAITING_APPROVAL"}]
        return active_exec + active_turns

    def stop(self, run_id: str, *, timeout_seconds: float = 5) -> BridgeRun:
        raw = self.registry.raw(run_id)
        if raw is None:
            raise KeyError(run_id)
        if raw["status"] not in {RunStatus.STARTING.value, RunStatus.RUNNING.value}:
            return self.get_run(run_id)
        control = self.state_dir / "control" / f"{run_id}.stop"
        control.parent.mkdir(parents=True, exist_ok=True)
        control.touch(exist_ok=True)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            record = self.get_run(run_id)
            if record.status not in {RunStatus.STARTING, RunStatus.RUNNING}:
                self._wait_worker_exit(run_id, timeout=timeout_seconds)
                return record
            time.sleep(0.05)
        record = self.get_run(run_id)
        if record.status in {RunStatus.STARTING, RunStatus.RUNNING}:
            return self.kill(run_id)
        return record

    def kill(self, run_id: str) -> BridgeRun:
        raw = self.registry.raw(run_id)
        if raw is None:
            raise KeyError(run_id)
        if raw.get("pid") and self._identity_alive(raw["pid"], raw["pid_identity"]):
            # Recheck identity immediately before the OS-level tree operation.
            if self._identity_alive(raw["pid"], raw["pid_identity"]):
                _terminate_tree(raw["pid"], force=True)
        if raw.get("worker_pid") and self._identity_alive(raw["worker_pid"], raw["worker_identity"]):
            if self._identity_alive(raw["worker_pid"], raw["worker_identity"]):
                _terminate_tree(raw["worker_pid"], force=True)
        self._wait_worker_exit(run_id, timeout=5)
        self.registry.update(run_id, status=RunStatus.STOPPED.value, last_error="Terminated by bridge kill")
        from .scheduler import ResourceScheduler
        scheduler = ResourceScheduler(self.registry.path)
        managed = scheduler.get(run_id)
        if managed and managed["status"] not in scheduler.TERMINAL:
            scheduler.finish(run_id, RunStatus.STOPPED.value, finished_at=datetime.now(timezone.utc).isoformat(), error="terminated by bridge kill")
            self.registry.add_run_event(run_id, "STOPPED", {"forced": True})
            from ._exec_dispatch import dispatch
            dispatch(self.registry.path)
        return self.get_run(run_id)

    def cancel(self, run_id: str, *, grace_seconds: float = 5) -> BridgeRun:
        """Cancel queued work or request controlled cancellation of a managed active run."""
        from datetime import datetime, timezone
        from .scheduler import ResourceScheduler
        scheduler = ResourceScheduler(self.registry.path)
        resolved = self.registry.resolve_reference(run_id)["run"]
        bridge_run_id = str(resolved["bridge_run_id"])
        scheduled = scheduler.get(bridge_run_id)
        if scheduled and scheduled["status"] in scheduler.QUEUED:
            scheduler.cancel(bridge_run_id, finished_at=datetime.now(timezone.utc).isoformat())
            self.registry.update(bridge_run_id, status=RunStatus.CANCELLED.value, last_error="Cancelled before execution started")
            self.registry.add_run_event(bridge_run_id, "CANCELLED", {})
            from ._exec_dispatch import dispatch
            dispatch(self.registry.path)
            return self.get_run(bridge_run_id)
        backend = str(resolved.get("backend", ""))
        if backend == "app-server":
            from .runtime_manager import request_app_server_cancel
            request_app_server_cancel(self.registry.path, bridge_run_id, timeout=grace_seconds)
            return self.get_run(bridge_run_id)
        if scheduled is None:
            return self.stop(bridge_run_id, timeout_seconds=grace_seconds)
        if scheduled["status"] in scheduler.TERMINAL:
            return self.get_run(bridge_run_id)
        scheduler.request_cancel(bridge_run_id)
        control = self.state_dir / "control"
        control.mkdir(parents=True, exist_ok=True)
        (control / f"{bridge_run_id}.cancel").touch(exist_ok=True)
        (control / f"{bridge_run_id}.stop").touch(exist_ok=True)
        deadline = time.monotonic() + max(0.1, grace_seconds)
        while time.monotonic() < deadline:
            current = scheduler.get(bridge_run_id)
            if current and current["status"] in scheduler.TERMINAL:
                self._wait_worker_exit(bridge_run_id, timeout=max(5, grace_seconds + 2))
                return self.get_run(bridge_run_id)
            time.sleep(0.05)
        current = scheduler.get(bridge_run_id)
        if current and current["status"] not in scheduler.TERMINAL:
            raw = self.registry.raw(bridge_run_id) or {}
            for key, identity_key in (("pid", "pid_identity"), ("worker_pid", "worker_identity")):
                pid, identity = raw.get(key), raw.get(identity_key)
                if pid and self._identity_alive(pid, identity) and self._identity_alive(pid, identity):
                    _terminate_tree(pid, force=True)
            self._wait_worker_exit(bridge_run_id, timeout=5)
            self.registry.update(bridge_run_id, status=RunStatus.CANCELLED.value, last_error="Cancelled; process terminated after grace period")
            scheduler.finish(bridge_run_id, RunStatus.CANCELLED.value, finished_at=datetime.now(timezone.utc).isoformat(), error="cancelled after grace period")
            self.registry.add_run_event(bridge_run_id, "CANCELLED", {"forced": True})
            from ._exec_dispatch import dispatch
            dispatch(self.registry.path)
        return self.get_run(bridge_run_id)

    def read_result(self, run_id: str) -> RunResult | None:
        raw = self.registry.raw(run_id)
        if raw is None:
            raise KeyError(run_id)
        self._wait_worker_exit(run_id, timeout=5)
        result_path = Path(raw["result_path"])
        if not result_path.is_file():
            return None
        data = json.loads(result_path.read_text(encoding="utf-8"))
        result_path.unlink(missing_ok=True)
        return RunResult(**data)

    def _wait_worker_exit(self, run_id: str, *, timeout: float) -> None:
        raw = self.registry.raw(run_id)
        if not raw or not raw.get("worker_pid"):
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self._identity_alive(raw["worker_pid"], raw["worker_identity"]):
            time.sleep(0.02)

    @staticmethod
    def _identity_alive(pid: int, identity: str | None) -> bool:
        if isinstance(pid, bool) or not isinstance(pid, int) or not identity:
            return False
        try:
            return _identity(pid) == identity
        except (OSError, ProcessLookupError, ValueError):
            return False

    def _validate_request(
        self,
        prompt: str,
        *,
        cwd: str | Path,
        profile: str,
        model: str | None,
        timeout_seconds: float | None,
        permissions: CodexPermissions | None,
        reasoning_effort: str | None,
        reasoning_summary: ReasoningSummary | str | None,
        verbosity: ModelVerbosity | str | None,
        output_schema: dict[str, Any] | None,
        capture_last_message: bool,
        include_raw_output: bool,
        config_policy: str | None,
        config_overrides: dict[str, Any] | None,
        security_policy: RunSecurityPolicy | None = None,
    ) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        selected = get_profile(profile)
        resolved_cwd = self.cwd_policy.resolve(cwd)
        timeout = self.default_timeout_seconds if timeout_seconds is None else timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 3600:
            raise ValueError("timeout_seconds must be in range (0, 3600]")
        if model is not None and (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:/+-]{1,100}", model)):
            raise ValueError("invalid model identifier")
        if reasoning_effort is not None and (not isinstance(reasoning_effort, str) or not reasoning_effort.strip() or len(reasoning_effort) > 32):
            raise ValueError("reasoning_effort must be a non-empty Codex-supported value")
        reasoning_summary_value = ReasoningSummary(reasoning_summary).value if reasoning_summary is not None else None
        verbosity_value = ModelVerbosity(verbosity).value if verbosity is not None else None
        if not isinstance(capture_last_message, bool) or not isinstance(include_raw_output, bool):
            raise ValueError("capture_last_message and include_raw_output must be booleans")
        if output_schema is not None and not isinstance(output_schema, dict):
            raise ValueError("output_schema must be a JSON object")
        if output_schema is not None:
            try:
                if len(json.dumps(output_schema, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
                    raise ValueError("output_schema exceeds the 1 MiB limit")
            except (TypeError, ValueError) as exc:
                raise ValueError("output_schema must be a JSON-serializable object below 1 MiB") from exc
        config_policy = str(config_policy or selected.config_policy)
        if config_policy == "user":
            raise ValueError("Codex CLI cannot isolate user-only configuration; use project for native layered configuration")
        if config_policy not in {item.value for item in ConfigPolicy}:
            raise ValueError("config_policy must be isolated, project or explicit")
        security_policy = security_policy or self.default_security_policy
        security_result = validate_run_security(security_policy, backend="exec", config_policy=config_policy, cwd=resolved_cwd)
        overrides = dict(config_overrides or {})
        supported_override_keys = {"model", "model_reasoning_effort", "model_reasoning_summary", "model_verbosity"}
        if any(key not in supported_override_keys for key in overrides):
            raise ValueError("unsupported Codex config override key; use typed API settings")
        typed_overrides = {
            key: value for key, value in {
                "model_reasoning_effort": reasoning_effort,
                "model_reasoning_summary": reasoning_summary_value,
                "model_verbosity": verbosity_value,
            }.items() if value is not None
        }
        for key, value in typed_overrides.items():
            if key in overrides:
                if overrides[key] != value:
                    raise ValueError(f"config override conflicts with typed setting: {key}")
                raise ValueError(f"do not repeat typed setting in config_overrides: {key}")
        if "model" in overrides:
            if model is not None and overrides["model"] != model:
                raise ValueError("config override conflicts with model")
            raise ValueError("use the typed model parameter instead of config_overrides['model']")
        if config_policy == "explicit" and not overrides and not typed_overrides and model is None:
            raise ValueError("config_overrides are required for explicit config_policy")
        if config_policy != "explicit" and overrides:
            raise ValueError("config_overrides require explicit config_policy")
        if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", key) for key in overrides):
            raise ValueError("invalid Codex config override key")
        for value in overrides.values():
            from .runtime import _toml_scalar
            _toml_scalar(value)
        for key in ("model_reasoning_summary", "model_verbosity"):
            if key in overrides:
                enum_type = ReasoningSummary if key == "model_reasoning_summary" else ModelVerbosity
                enum_type(overrides[key])
        actual_permissions = permissions or selected.permissions
        if not isinstance(actual_permissions, CodexPermissions):
            raise ValueError("permissions must be CodexPermissions")
        sandbox = SandboxMode(actual_permissions.sandbox)
        approval = ApprovalPolicy(actual_permissions.approval_policy)
        if sandbox == SandboxMode.FULL_ACCESS and approval != ApprovalPolicy.ON_REQUEST:
            raise ValueError("danger-full-access requires explicit on-request approval policy")
        if not isinstance(actual_permissions.network_access, (bool, type(None))):
            raise ValueError("network_access must be true, false or None")
        if actual_permissions.network_access is not None and sandbox != SandboxMode.WORKSPACE_WRITE:
            raise ValueError("exec exposes network_access through workspace-write sandbox config only")
        roots = self.cwd_policy.resolve_writable_roots(actual_permissions.writable_roots, cwd=resolved_cwd)
        if roots and sandbox != SandboxMode.WORKSPACE_WRITE:
            raise ValueError("writable_roots require workspace-write sandbox")
        network_access = actual_permissions.network_access
        if sandbox == SandboxMode.WORKSPACE_WRITE and network_access is None:
            network_access = False
        return {
            "prompt": prompt,
            "cwd": str(resolved_cwd),
            "profile": profile,
            "model": model,
            "timeout_seconds": float(timeout),
            "permissions": {"sandbox": sandbox.value, "approval_policy": approval.value},
            "reasoning_effort": reasoning_effort,
            "reasoning_summary": reasoning_summary_value,
            "verbosity": verbosity_value,
            "writable_roots": [str(path) for path in roots],
            "network_access": network_access,
            "output_schema": output_schema,
            "capture_last_message": capture_last_message,
            "include_raw_output": include_raw_output,
            "config_policy": config_policy,
            "config_overrides": overrides,
            "security_policy": security_policy.to_dict(),
            "security_snapshot": {"project_trust": security_policy.project_trust.value,
                                  "policy_id": security_result.policy_id,
                                  "risk_acknowledged": security_policy.explicit_risk_acknowledgement,
                                  "mcp_isolation_required": security_policy.require_mcp_isolation,
                                  "decision": security_result.decision.value},
        }
