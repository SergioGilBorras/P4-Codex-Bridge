from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from typing import Any

from .client import CodexBridge
from .runtime import redact
from . import __version__


def _read_json() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("input exceeds the 2 MiB limit")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("stdin must contain a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="p4-codex")
    parser.add_argument("--version", action="version", version=f"p4-codex {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
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
    args = parser.parse_args(argv)
    try:
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
            if args.json:
                output, code = rows, 0
            else:
                headers = ("RUN ID", "STATUS", "AGENT", "TASK", "BACKEND", "WORKSPACE", "ACCESS", "QUEUE_POS", "WAIT_REASON", "AGE")
                table = [headers]
                for row in rows:
                    from datetime import datetime, timezone
                    try: age = time.strftime("%H:%M:%S", time.gmtime(max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(row["started_at"])).total_seconds())))
                    except (ValueError, TypeError): age = "?"
                    meta = row.get("agent_metadata", {})
                    table.append(tuple(str(v or "-") for v in (row.get("bridge_run_id"), row.get("status"), meta.get("agent_name"), meta.get("task_key"), row.get("backend"), row.get("workspace") or row.get("cwd"), row.get("access_mode"), row.get("queue_position"), row.get("waiting_reason"), age)))
                widths = [max(len(str(row[i])) for row in table) for i in range(len(headers))]
                for row in table: sys.stdout.write("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)).rstrip() + "\n")
                return 0
        elif args.command == "inspect":
            output, code = bridge.inspect(args.run_id), 0
        elif args.command == "watch":
            for event in bridge.watch(args.run_id, task=args.task, agent=args.agent, follow=args.follow,
                                      no_deltas=args.no_deltas, tools=args.tools, approvals=args.approvals, since=args.since):
                if args.json:
                    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
                else:
                    kind = event.get("type")
                    data = event.get("data", {})
                    if kind == "AgentMessageCompleted": message = data.get("final_text", "")
                    elif kind == "AgentMessageDelta": message = data.get("partial_text", data.get("delta", ""))
                    else: message = json.dumps(data, ensure_ascii=False)
                    sys.stdout.write(f"[{event.get('timestamp', '')}] {kind}: {message}\n")
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
        sys.stderr.write(redact(str(exc)) + "\n")
        sys.stdout.write(json.dumps({"ok": False, "error": {"code": "BRIDGE_ERROR", "message": redact(str(exc))}}, ensure_ascii=False) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
