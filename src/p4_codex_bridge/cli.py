from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from typing import Any

from . import __version__


class JsonArgumentParser(argparse.ArgumentParser):
    """Keep usage failures inside the documented JSON stdout contract."""

    def error(self, message: str) -> None:
        del message  # Avoid reflecting arbitrary argv values into logs/output.
        error = {"ok": False, "error": {"code": "USAGE_ERROR", "message": "invalid command arguments"}}
        sys.stdout.write(json.dumps(error, ensure_ascii=False) + "\n")
        sys.stderr.write("invalid command arguments\n")
        raise SystemExit(2)


def _add_service_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config")
    parser.add_argument("--state-dir")


def _read_json() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("input exceeds the 2 MiB limit")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("stdin must contain a JSON object")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="p4-codex")
    parser.add_argument("--version", action="version", version=f"p4-codex {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--announce", action="store_true")
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--announce", action="store_true")
    ps = sub.add_parser("ps")
    ps.add_argument("--active", action="store_true")
    ps.add_argument("--task")
    ps.add_argument("--agent")
    ps.add_argument("--backend")
    ps.add_argument("--status")
    ps.add_argument("--json", action="store_true")
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("run_id")
    watch = sub.add_parser("watch")
    watch.add_argument("run_id", nargs="?")
    watch.add_argument("--task")
    watch.add_argument("--agent")
    watch.add_argument("--follow", action="store_true")
    watch.add_argument("--json", action="store_true")
    watch.add_argument("--no-deltas", action="store_true")
    watch.add_argument("--tools", action=argparse.BooleanOptionalAction, default=True)
    watch.add_argument("--approvals", action=argparse.BooleanOptionalAction, default=True)
    watch.add_argument("--since")
    for command in ("status", "result", "stop", "kill"):
        command_parser = sub.add_parser(command)
        command_parser.add_argument("run_id")
    sub.add_parser("models")
    events = sub.add_parser("events")
    events.add_argument("turn_id", nargs="?")
    events.add_argument("--thread")
    events.add_argument("--follow", action="store_true")
    events.add_argument("--json", action="store_true")
    sub.add_parser("approvals")
    for command in ("approve", "reject"):
        approval = sub.add_parser(command)
        approval.add_argument("approval_id")
    sub.add_parser("capabilities")
    sub.add_parser("version")
    sub.add_parser("resources")
    sub.add_parser("limits")
    cancel_parser = sub.add_parser("cancel")
    cancel_parser.add_argument("run_id")
    service = sub.add_parser("service")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    service_run = service_sub.add_parser("run")
    _add_service_paths(service_run)
    service_run.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)
    for name in ("status", "stop", "restart", "recover", "demo"):
        command = service_sub.add_parser(name)
        _add_service_paths(command)
        command.add_argument("--json", action="store_true")
        if name in {"stop", "restart", "recover", "demo"}:
            command.add_argument("--timeout", type=float, default=30)
    health = sub.add_parser("health")
    _add_service_paths(health)
    health.add_argument("--json", action="store_true")
    metrics = sub.add_parser("metrics")
    _add_service_paths(metrics)
    metrics.add_argument("--json", action="store_true")
    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    for name in ("show", "validate"):
        command = config_sub.add_parser(name)
        _add_service_paths(command)
    doctor = sub.add_parser("doctor")
    _add_service_paths(doctor)
    doctor.add_argument("--json", action="store_true")
    maintenance = sub.add_parser("maintenance")
    maintenance_sub = maintenance.add_subparsers(dest="maintenance_command", required=True)
    for name in ("status", "clean"):
        command = maintenance_sub.add_parser(name)
        _add_service_paths(command)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--json", action="store_true")
    submit = sub.add_parser("submit")
    submit_sub = submit.add_subparsers(dest="submit_command", required=True)
    submit_exec = submit_sub.add_parser("exec")
    submit_exec.add_argument("--wait", type=float, default=30)
    submit_exec.add_argument("--json", action="store_true")
    _add_service_paths(submit_exec)
    thread = sub.add_parser("thread")
    thread_sub = thread.add_subparsers(dest="thread_command", required=True)
    thread_create = thread_sub.add_parser("create")
    thread_create.add_argument("--wait", type=float, default=30)
    thread_create.add_argument("--json", action="store_true")
    _add_service_paths(thread_create)
    turn = sub.add_parser("turn")
    turn_sub = turn.add_subparsers(dest="turn_command", required=True)
    turn_start = turn_sub.add_parser("start")
    turn_start.add_argument("--wait", type=float, default=30)
    turn_start.add_argument("--json", action="store_true")
    _add_service_paths(turn_start)
    # The registry is intentionally shared by service and non-service commands.
    # This flag lets an operator point any CLI view/control command at that same DB.
    for command_parser in sub.choices.values():
        if not any("--state-dir" in action.option_strings for action in command_parser._actions):
            command_parser.add_argument("--state-dir", help=argparse.SUPPRESS)
    # Every leaf command accepts --json. Machine-readable JSON/JSONL is the
    # stdout contract, so this flag is explicit for scripts but not required.
    def add_json_options(command_parser: argparse.ArgumentParser) -> None:
        if command_parser is not parser and not any("--json" in action.option_strings for action in command_parser._actions):
            command_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON (the default)")
        for action in command_parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child_parser in action.choices.values():
                    add_json_options(child_parser)
    add_json_options(parser)
    return parser


def _error_exit_code(exc: Exception) -> int:
    from .errors import (BackendError, BridgeTimeoutError, CapabilityUnavailableError,
                         ConflictError, QueueFullError, ResourceUnavailableError,
                         RunNotFoundError, RunSecurityRejectedError, RunStateError,
                         ServiceUnavailableError, ConfigurationError)
    from .events import (ApprovalError, ApprovalTimeoutError, EventDecodeError,
                         EventStreamError, ToolEventError)
    if isinstance(exc, RunSecurityRejectedError): return 3
    if isinstance(exc, CapabilityUnavailableError): return 4
    if isinstance(exc, (BridgeTimeoutError, ApprovalTimeoutError, TimeoutError)): return 6
    if isinstance(exc, (ApprovalError, ConflictError)): return 8
    if isinstance(exc, (EventDecodeError, EventStreamError, ToolEventError)): return 7
    if isinstance(exc, (ConflictError, QueueFullError, ResourceUnavailableError,
                        RunNotFoundError, RunStateError)): return 8
    if isinstance(exc, BackendError): return 7
    if isinstance(exc, (ServiceUnavailableError, ConnectionError, FileNotFoundError)): return 5
    if isinstance(exc, (ConfigurationError, ValueError, TypeError)): return 2
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "state_dir", None):
        os.environ["P4_CODEX_BRIDGE_STATE_DIR"] = str(args.state_dir)
    try:
        if args.command in {"service", "health", "metrics", "config", "doctor", "maintenance"}:
            from .service import (ForegroundService, ServiceConfig, default_state_dir, doctor_report,
                                  fake_app_server_command, launch_service, request_service_action,
                                  service_metrics, service_status, validate_config, database_health, maintenance_report)
            config_path = getattr(args, "config", None) or os.environ.get("P4_CODEX_BRIDGE_CONFIG")
            state_override = getattr(args, "state_dir", None)
            if args.command == "config":
                report = validate_config(config_path, state_dir=state_override)
                if args.config_command == "show":
                    output = report["config"]
                else:
                    output = report
                sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
                return 0
            cfg = ServiceConfig.load(config_path, state_dir=state_override)
            if args.command == "maintenance":
                report = maintenance_report(cfg.state_dir, cfg, dry_run=(args.maintenance_command == "status" or args.dry_run))
                sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
                return 0 if report.get("available") else 1
            if args.command == "service":
                if args.service_command == "run":
                    return ForegroundService(cfg, fake_command=fake_app_server_command() if args.fake else None).run()
                if args.service_command == "status":
                    data = service_status(cfg.state_dir)
                    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
                    return 0 if data.get("state") in {"HEALTHY", "DEGRADED", "STOPPED"} else 1
                if args.service_command == "stop":
                    output = request_service_action(cfg.state_dir, "stop", timeout=args.timeout)
                elif args.service_command == "recover":
                    output = request_service_action(cfg.state_dir, "recover", timeout=args.timeout)
                elif args.service_command == "demo":
                    output = request_service_action(cfg.state_dir, "demo", timeout=args.timeout)
                else:
                    output = launch_service(config_path=config_path, state_dir=state_override, timeout=args.timeout)
                sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
                return 0 if output.get("status", "COMPLETED") in {"COMPLETED", "ACCEPTED"} else 1
            if args.command == "health":
                data = service_status(cfg.state_dir)
                data["database"] = database_health(cfg.state_dir, retention_days=cfg.retention_days)
                db_report = data["database"]
                if db_report.get("available") and (db_report.get("integrity") != "ok" or db_report.get("migration_status") not in {"CURRENT", "MIGRATION_REQUIRED"}):
                    data["state"] = "DEGRADED"
                    data["reason"] = "database integrity or schema status requires attention"
                sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
                return 0 if data.get("state") in {"HEALTHY", "DEGRADED"} else 1
            if args.command == "metrics":
                data = service_metrics(cfg.state_dir)
                sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
                return 0 if data.get("available", True) else 1
            if args.command == "doctor":
                from .service import doctor_report
                output = doctor_report(cfg)
                sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
                return 0 if output["ok"] else 1
        if args.command in {"submit", "thread", "turn"}:
            from .service_client import (CodexServiceClient, ExecRunSubmission,
                CreateThreadRequest, StartTurnRequest)
            from .models import ApprovalPolicy, SandboxMode
            from .permissions import CodexPermissions
            from .security import RunSecurityPolicy
            request = _read_json()
            client = CodexServiceClient(state_dir=getattr(args, "state_dir", None), config_path=getattr(args, "config", None))
            idempotency_key = request.pop("idempotency_key", None)
            security_data = request.pop("security_policy", None)
            if security_data is not None:
                request["security_policy"] = RunSecurityPolicy.from_dict(security_data)
            if args.command == "submit":
                permissions_data = request.pop("permissions", None)
                if permissions_data is not None:
                    permissions_data["sandbox"] = SandboxMode(permissions_data["sandbox"])
                    permissions_data["approval_policy"] = ApprovalPolicy(permissions_data["approval_policy"])
                    permissions_data["writable_roots"] = tuple(permissions_data.get("writable_roots", ()))
                    request["permissions"] = CodexPermissions(**permissions_data)
                result = client.submit_exec_run(ExecRunSubmission(**request), idempotency_key=idempotency_key, timeout=args.wait)
            elif args.command == "thread":
                result = client.create_thread(CreateThreadRequest(**request), idempotency_key=idempotency_key, timeout=args.wait)
            else:
                result = client.start_turn(StartTurnRequest(**request), idempotency_key=idempotency_key, timeout=args.wait)
            output = asdict(result)
            sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
            return 0 if result.status in {"COMPLETED", "SUBMITTED", "CLAIMED"} else 1
        from .client import CodexBridge
        bridge = CodexBridge()
        if args.command in {"run", "start"}:
            request = _read_json()
            prompt = request.pop("prompt", None)
            cwd = request.pop("cwd", None)
            announce = bool(request.pop("announce_run", False) or getattr(args, "announce", False))
            if args.command == "run":
                timeout = request.get("timeout_seconds")
                record = bridge._start_direct(prompt, cwd=cwd, announce_run=False, **request)
                if announce: sys.stderr.write(bridge.format_run_announcement(record.bridge_run_id) + "\n")
                result = bridge._collect_result(record, timeout)
                if announce:
                    elapsed = time.strftime("%H:%M:%S", time.gmtime(result.duration_ms / 1000))
                    sys.stderr.write(f"[P4-Codex] {'Completed' if result.ok else 'Failed'} {record.bridge_run_id} | {'SUCCESS' if result.ok else 'FAILED'} | {elapsed}\n")
                output = asdict(result)
                code = 0 if result.ok else 1
            else:
                record = bridge.start(prompt, cwd=cwd, announce_run=announce, **request)
                if announce: sys.stderr.write(bridge.format_run_announcement(record.bridge_run_id) + "\n")
                output, code = record.to_dict(), 0
        elif args.command == "ps":
            rows = bridge.discover_runs(active=args.active, task=args.task, agent=args.agent, backend=args.backend, status=args.status)
            output, code = rows, 0
        elif args.command == "inspect":
            output, code = bridge.inspect(args.run_id), 0
        elif args.command == "watch":
            for event in bridge.watch(args.run_id, task=args.task, agent=args.agent, follow=args.follow,
                                      no_deltas=args.no_deltas, tools=args.tools, approvals=args.approvals, since=args.since):
                sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
            return 0
        elif args.command == "status":
            record = bridge.status(args.run_id)
            output, code = record.to_dict() if hasattr(record, "to_dict") else record, 0
        elif args.command == "result":
            result = bridge.read_result(args.run_id)
            output, code = (asdict(result) if result else None), 0
        elif args.command == "stop":
            output, code = bridge.stop(args.run_id).to_dict(), 0
        elif args.command == "kill":
            output, code = bridge.kill(args.run_id).to_dict(), 0
        elif args.command == "models":
            output, code = bridge.list_models(), 0
        elif args.command == "events":
            sequence = 0
            while True:
                events_out = bridge.get_events(thread_id=args.thread, turn_id=args.turn_id, after_sequence=sequence)
                for event in events_out:
                    sequence = max(sequence, int(event["persistence_sequence"]))
                    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
                if not args.follow:
                    return 0
                time.sleep(0.25)
        elif args.command == "approvals":
            output, code = bridge.list_pending_approvals(), 0
        elif args.command in {"approve", "reject"}:
            getattr(bridge, args.command)(args.approval_id)
            output, code = {"ok": True, "approval_id": args.approval_id, "decision": "accept" if args.command == "approve" else "decline"}, 0
        elif args.command in {"resources", "limits", "cancel"}:
            from .scheduler import ResourceScheduler, RuntimeLimits
            scheduler = ResourceScheduler(bridge.state_dir / "runs.sqlite3")
            if args.command == "resources": output, code = scheduler.resources(), 0
            elif args.command == "limits": output, code = scheduler.get_persisted_limits() or RuntimeLimits().__dict__, 0
            else:
                output, code = bridge.cancel(args.run_id).to_dict(), 0
        elif args.command == "capabilities":
            output, code = bridge.get_capabilities(), 0
        else:
            output, code = {"version": bridge.get_version()}, 0
        sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
        return code
    except Exception as exc:
        from .runtime import redact
        from .errors import BridgeError
        public_message = redact(str(exc)) if isinstance(exc, BridgeError) else "operation failed; see sanitized diagnostics"
        sys.stderr.write(public_message + "\n")
        code = _error_exit_code(exc)
        error_name = ("VALIDATION_ERROR" if isinstance(exc, (ValueError, TypeError)) else
                      "SERVICE_UNAVAILABLE" if isinstance(exc, (ConnectionError, FileNotFoundError)) else
                      type(exc).__name__ if isinstance(exc, BridgeError) else "BRIDGE_ERROR")
        sys.stdout.write(json.dumps({"ok": False, "error": {"code": error_name, "message": public_message}}, ensure_ascii=False) + "\n")
        return code


if __name__ == "__main__":
    raise SystemExit(main())
