from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Iterator

from . import __version__
from .events import ApprovalError, ApprovalRequest, CodexEvent, EventDecodeError, EventNormalizer, EventStreamError, EventSubscription, _safe, decode_json_line
from .models import AppServerApprovalPolicy, ApprovalHandlingPolicy, SandboxMode
from .runtime import codex_environment, redact, resolve_codex_command
from .registry import RunRegistry


class AppServerConnection:
    """One stdio app-server connection; one reader demultiplexes RPC and notifications."""

    def __init__(self, *, cwd: str | Path, approval_timeout_seconds: float = 300, approval_timeout_policy: str = "reject", approval_policy: ApprovalHandlingPolicy = ApprovalHandlingPolicy.MANUAL, queue_size: int = 256, registry: RunRegistry | None = None):
        self.cwd = str(cwd)
        self.thread_id: str | None = None
        self.turn_id: str | None = None
        self.approval_timeout_seconds = approval_timeout_seconds
        if approval_timeout_policy not in {"reject", "error"}:
            raise ValueError("approval_timeout_policy must be reject or error")
        self.approval_timeout_policy = approval_timeout_policy
        self.approval_handling_policy = ApprovalHandlingPolicy(approval_policy)
        self.registry = registry
        self._default_subscription = EventSubscription(maxsize=queue_size)
        self._subscribers: set[EventSubscription] = {self._default_subscription}
        self.process = subprocess.Popen(
            resolve_codex_command() + ["app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=self.cwd, env=codex_environment(), shell=False, bufsize=0,
        )
        self.normalizer = EventNormalizer()
        self._write_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._event_publish_lock = threading.Lock()
        self._event_sequence = 0
        self._pending: dict[int, queue.Queue] = {}
        self._next_id = 0
        self._approvals: dict[str, dict[str, Any]] = {}
        self._deadline_threads: set[threading.Thread] = set()
        self._deadline_threads_lock = threading.Lock()
        self._pending_approval: ApprovalRequest | None = None
        self._state = "STARTING"
        self._message_delta = ""
        self._final_text = ""
        self._stop = threading.Event()
        self.events_received = 0
        self.events_dropped = 0
        self._reader = threading.Thread(target=self._read_loop, args=(queue_size,), daemon=True)
        self._reader.start()
        self._approval_watcher = threading.Thread(target=self._watch_approval_decisions, daemon=True)
        self._approval_watcher.start()

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    @property
    def pending_approval(self) -> ApprovalRequest | None:
        with self._state_lock:
            return self._pending_approval

    @property
    def partial_text(self) -> str:
        with self._state_lock:
            return self._message_delta

    @property
    def final_text(self) -> str:
        with self._state_lock:
            return self._final_text

    def _local_event(self, event_type: str, *, thread_id: str | None = None, turn_id: str | None = None, data: dict[str, Any] | None = None, raw: dict[str, Any] | None = None) -> CodexEvent:
        return CodexEvent(event_type, datetime.now(timezone.utc).isoformat(), thread_id, turn_id, self.normalizer.next_sequence(), data or {}, _safe(raw) if raw else None)

    def subscribe(self, *, thread_id: str | None = None, turn_id: str | None = None, queue_size: int = 256) -> EventSubscription:
        subscription = EventSubscription(maxsize=queue_size, thread_id=thread_id, turn_id=turn_id)
        with self._state_lock:
            self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        with self._state_lock:
            self._subscribers.discard(subscription)
        subscription.close()

    def _send(self, message: dict[str, Any]) -> None:
        if not self.process.stdin or self.process.poll() is not None:
            raise EventStreamError("Codex app-server is not running")
        encoded = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._write_lock:
            self.process.stdin.write(encoded)
            self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 30) -> dict[str, Any]:
        with self._state_lock:
            self._next_id += 1
            request_id = self._next_id
            response_queue: queue.Queue = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            try:
                response = response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise TimeoutError(f"Codex app-server request timed out: {method}") from exc
            if isinstance(response, BaseException):
                raise response
            if "error" in response:
                error = response.get("error", {})
                raise EventStreamError(redact(str(error.get("message", "Codex app-server request failed"))))
            result = response.get("result", {})
            return result if isinstance(result, dict) else {}
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _read_loop(self, queue_size: int) -> None:
        try:
            assert self.process.stdout is not None
            while not self._stop.is_set():
                line = self.process.stdout.readline()
                if not line:
                    break
                try:
                    message = decode_json_line(line.decode("utf-8", "replace"))
                except EventDecodeError as exc:
                    self._publish(self._local_event("ServerError", data={"code": "EVENT_DECODE_ERROR", "message": str(exc)}))
                    continue
                if "id" in message and ("result" in message or "error" in message):
                    with self._state_lock:
                        target = self._pending.get(message["id"])
                    if target:
                        target.put(message)
                    continue
                if "method" not in message:
                    continue
                if "id" in message:
                    self._handle_server_request(message)
                else:
                    try:
                        event = self.normalizer.normalize(message)
                    except EventDecodeError as exc:
                        event = self._local_event("ServerError", data={"code": "EVENT_DECODE_ERROR", "message": str(exc)}, raw=message)
                    self.events_received += 1
                    self._publish(event)
                    self._update_state(event)
        except (OSError, ValueError) as exc:
            if not self._stop.is_set():
                self._fail_waiters(EventStreamError(redact(str(exc))))
        finally:
            self._fail_waiters(EventStreamError("Codex app-server stream closed"))
            if not self._stop.is_set():
                with self._state_lock:
                    pending = [(key, value["request"]) for key, value in self._approvals.items()]
                    self._approvals.clear()
                    self._pending_approval = None
                for approval_id, request in pending:
                    if self.registry:
                        self.registry.upsert_approval(request, status="RESOLVED", decision="cancel")
                    self._publish(self._local_event("ApprovalResolved", thread_id=request.thread_id, turn_id=request.turn_id,
                                                    data={"approval_id": approval_id, "decision": "cancel", "reason": "app-server exited"}))
                self._publish(self._local_event("ServerError", thread_id=self.thread_id, turn_id=self.turn_id,
                                                data={"code": "APP_SERVER_CRASH", "message": "Codex app-server stream closed unexpectedly"}))
                with self._state_lock:
                    self._state = "FAILED"

    def _handle_server_request(self, message: dict[str, Any]) -> None:
        method = message.get("method", "")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method not in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/permissions/requestApproval"}:
            self._send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Bridge does not handle this app-server request"}})
            self._publish(self._local_event("ServerError", thread_id=params.get("threadId"), turn_id=params.get("turnId"), data={"code": "UNHANDLED_SERVER_REQUEST", "method": method}, raw=message))
            return
        approval_id = f"{params.get('threadId','')}:{params.get('turnId','')}:{message['id']}"
        request = ApprovalRequest(
            approval_id=approval_id, method=method, thread_id=params.get("threadId"), turn_id=params.get("turnId"),
            item_id=params.get("itemId"), action=_safe(params.get("commandActions") or params.get("permissions")),
            tool=params.get("toolName"), arguments=_safe(params.get("command")), reason=redact(str(params.get("reason") or "")) or None,
            raw=_safe(message),
        )
        with self._state_lock:
            self._approvals[approval_id] = {"rpc_id": message["id"], "method": method, "request": request, "created": time.monotonic()}
            self._pending_approval = request
            self._state = "WAITING_APPROVAL"
        if self.registry:
            self.registry.upsert_approval(request, status="PENDING")
        event = self._local_event("ApprovalRequested", thread_id=request.thread_id, turn_id=request.turn_id, data={"approval": request.__dict__}, raw=message)
        self._publish(event)
        if self.approval_handling_policy in {ApprovalHandlingPolicy.AUTO_REJECT, ApprovalHandlingPolicy.NEVER_EXPECT_APPROVAL}:
            self.reject(approval_id, reason="rejected by explicit bridge approval policy")
            return
        deadline = threading.Thread(target=self._approval_deadline, args=(approval_id,), name=f"p4-codex-approval-{approval_id}", daemon=True)
        with self._deadline_threads_lock:
            self._deadline_threads.add(deadline)
        deadline.start()

    def _watch_approval_decisions(self) -> None:
        while not self._stop.wait(0.1):
            if not self.registry:
                continue
            try:
                for row in self.registry.pending_approval_decisions():
                    approval_id = row["approval_id"]
                    if approval_id in self._approvals:
                        self.resolve_approval(approval_id, row["payload"].get("decision", "decline"))
            except Exception:
                continue

    def _approval_deadline(self, approval_id: str) -> None:
        if self._stop.wait(self.approval_timeout_seconds):
            return
        with self._state_lock:
            if approval_id not in self._approvals:
                return
            request = self._approvals[approval_id]["request"]
        if self.approval_timeout_policy == "error":
            self._publish(self._local_event("ServerError", thread_id=request.thread_id,
                turn_id=request.turn_id,
                data={"code": "APPROVAL_TIMEOUT", "message": "Approval timed out and was rejected"}))
        decision = "cancel" if self.approval_timeout_policy == "error" else "decline"
        try:
            self.resolve_approval(approval_id, decision, reason="approval timeout")
        except Exception:
            return

    def resolve_approval(self, approval_id: str, decision: str, *, reason: str | None = None) -> None:
        with self._state_lock:
            pending = self._approvals.get(str(approval_id))
            if pending is None:
                raise ApprovalError("pending approval not found or already resolved")
            method = pending["method"]
            rpc_id = pending["rpc_id"]
            request: ApprovalRequest = pending["request"]
        if decision not in {"accept", "decline", "cancel"}:
            raise ValueError("decision must be accept, decline or cancel")
        if method == "item/permissions/requestApproval":
            result: dict[str, Any] = {"permissions": None} if decision != "accept" else {"permissions": _safe(request.action)}
        else:
            result = {"decision": decision}
        self._send({"jsonrpc": "2.0", "id": rpc_id, "result": result})
        with self._state_lock:
            self._approvals.pop(str(approval_id), None)
            self._pending_approval = next((v["request"] for v in self._approvals.values()), None)
            if not self._approvals and self._state == "WAITING_APPROVAL":
                self._state = "RUNNING"
        self._publish(self._local_event("ApprovalResolved", thread_id=request.thread_id, turn_id=request.turn_id, data={"approval_id": str(approval_id), "decision": decision, "reason": reason}))
        if self.registry:
            self.registry.upsert_approval(request, status="RESOLVED", decision=decision)

    def approve(self, approval_id: str) -> None:
        self.resolve_approval(approval_id, "accept")

    def reject(self, approval_id: str, *, reason: str = "") -> None:
        self.resolve_approval(approval_id, "decline", reason=reason or None)

    def _update_state(self, event: CodexEvent) -> None:
        with self._state_lock:
            if self._state in {"STOPPING", "STOPPED"}:
                return
            if event.type == "TurnStarted":
                self._state = "RUNNING"
                self._message_delta = ""
            elif event.type == "AgentMessageDelta":
                self._message_delta = event.data.get("partial_text", self._message_delta)
            elif event.type == "AgentMessageCompleted":
                self._final_text = event.data.get("final_text", self._message_delta)
            elif event.type == "TurnCompleted":
                turn = event.data.get("turn", {})
                self._state = str(turn.get("status", "completed")).upper()
            elif event.type in {"TurnFailed", "ServerError"}:
                self._state = "FAILED"
                if getattr(self, "announce_run", False):
                    import logging
                    logging.getLogger("p4_codex_bridge.announce").error("[P4-Codex] Failed %s | %s", getattr(self, "bridge_run_id", ""), str(event.data.get("message", "Codex turn failed"))[:300])
            elif event.type == "TurnInterrupted":
                self._state = "INTERRUPTED"
            if event.type == "TurnCompleted" and getattr(self, "announce_run", False):
                import logging
                status = str(event.data.get("turn", {}).get("status", "completed")).upper()
                logging.getLogger("p4_codex_bridge.announce").info("[P4-Codex] Completed %s | %s", getattr(self, "bridge_run_id", ""), status)

    def _publish(self, event: CodexEvent) -> None:
        with self._event_publish_lock:
            self._event_sequence += 1
            event = replace(event, sequence=self._event_sequence)
            if self.registry:
                self.registry.add_turn_event(event)
                status = {"TurnCompleted": "COMPLETED", "TurnFailed": "FAILED", "ServerError": "FAILED", "TurnInterrupted": "INTERRUPTED", "TurnStopped": "STOPPED", "ApprovalRequested": "WAITING_APPROVAL", "ApprovalResolved": "RUNNING"}.get(event.type)
                if status and event.turn_id:
                    self.registry.update_by_turn(event.turn_id, status=status, error=event.data.get("message") if status == "FAILED" else None)
            with self._state_lock:
                subscribers = tuple(self._subscribers)
            for subscription in subscribers:
                before = subscription.dropped
                subscription.publish(event)
                self.events_dropped += subscription.dropped - before

    def _fail_waiters(self, error: BaseException) -> None:
        with self._state_lock:
            waiters = tuple(self._pending.values())
        for target in waiters:
            try:
                target.put_nowait(error)
            except queue.Full:
                pass

    def close(self, *, timeout: float = 3) -> None:
        if self._stop.is_set():
            return
        with self._state_lock:
            active = self._state in {"STARTING", "RUNNING", "WAITING_APPROVAL"}
            if active:
                self._state = "STOPPING"
            approval_ids = tuple(self._approvals) if active else ()
        if active:
            for approval_id in approval_ids:
                try:
                    self.resolve_approval(approval_id, "cancel", reason="bridge turn closed")
                except Exception:
                    pass
            self._publish(self._local_event("TurnStopped", thread_id=self.thread_id, turn_id=self.turn_id, data={"reason": "bridge turn closed"}))
        self._stop.set()
        with self._state_lock:
            self._state = "STOPPED" if self._state not in {"COMPLETED", "FAILED", "INTERRUPTED"} else self._state
            subscriptions = tuple(self._subscribers)
        for subscription in subscriptions:
            subscription.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self._reader.join(timeout=timeout)
        self._approval_watcher.join(timeout=timeout)
        with self._deadline_threads_lock:
            deadline_threads = tuple(self._deadline_threads)
        for thread in deadline_threads:
            if thread is not threading.current_thread():
                thread.join(timeout=timeout)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass


class CodexTurn:
    """A live app-server turn and its event subscriptions/approval controls."""

    def __init__(self, connection: AppServerConnection, thread_id: str, turn_id: str):
        self.connection = connection
        self.thread_id = thread_id
        self.turn_id = turn_id
        self._default_subscription = connection._default_subscription

    @property
    def status(self) -> str:
        return self.connection.state

    @property
    def partial_text(self) -> str:
        return self.connection.partial_text

    @property
    def final_text(self) -> str:
        return self.connection.final_text

    @property
    def pending_approval(self) -> ApprovalRequest | None:
        return self.connection.pending_approval

    def events(self, *, timeout: float | None = 300) -> Iterator[CodexEvent]:
        start = time.monotonic()
        while True:
            remaining = None if timeout is None else timeout - (time.monotonic() - start)
            if remaining is not None and remaining <= 0:
                if self.status in {"RUNNING", "WAITING_APPROVAL"}:
                    try:
                        self.interrupt()
                    except Exception:
                        pass
                raise TimeoutError("event stream timed out")
            try:
                event = self._default_subscription.queue.get(timeout=min(remaining, 0.25) if remaining is not None else 0.25)
            except queue.Empty:
                if self.status in {"COMPLETED", "FAILED", "INTERRUPTED", "STOPPED"}:
                    return
                if remaining is not None and remaining <= 0:
                    if self.status in {"RUNNING", "WAITING_APPROVAL"}:
                        try: self.interrupt()
                        except Exception: pass
                    raise TimeoutError("event stream timed out")
                continue
            if event is None:
                return
            if isinstance(event, BaseException):
                raise event
            if event.thread_id not in (None, self.thread_id) or event.turn_id not in (None, self.turn_id):
                continue
            yield event
            if event.type in {"TurnCompleted", "TurnFailed", "TurnInterrupted", "TurnStopped"}:
                return

    def subscribe(self, *, queue_size: int = 256) -> EventSubscription:
        return self.connection.subscribe(thread_id=self.thread_id, turn_id=self.turn_id, queue_size=queue_size)

    def detach_event_consumer(self) -> None:
        """Detach an abandoned iterator so its full queue cannot stall the protocol reader."""
        self.connection.unsubscribe(self._default_subscription)
        self._default_subscription = self.connection.subscribe(thread_id=self.thread_id, turn_id=self.turn_id)

    def approve(self, approval_id: str) -> None:
        self.connection.approve(approval_id)

    def reject(self, approval_id: str) -> None:
        self.connection.reject(approval_id)

    def interrupt(self) -> None:
        self.connection.request("turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id})

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "CodexTurn":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def start_turn(
    prompt: str,
    *,
    cwd: str | Path,
    model: str | None = None,
    sandbox: SandboxMode = SandboxMode.READ_ONLY,
    approval_policy: AppServerApprovalPolicy = AppServerApprovalPolicy.NEVER,
    reasoning_effort: str | None = None,
    output_schema: dict[str, Any] | None = None,
    writable_roots: tuple[str | Path, ...] = (),
    network_access: bool | None = None,
    approval_timeout_seconds: float = 300,
    approval_timeout_policy: str = "reject",
    approval_handling_policy: ApprovalHandlingPolicy = ApprovalHandlingPolicy.MANUAL,
    queue_size: int = 256,
    registry: RunRegistry | None = None,
) -> CodexTurn:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt is required")
    if isinstance(approval_timeout_seconds, bool) or not isinstance(approval_timeout_seconds, (int, float)) or not 0 < approval_timeout_seconds <= 3600:
        raise ValueError("approval_timeout_seconds must be in range (0, 3600]")
    if approval_timeout_policy not in {"reject", "error"}:
        raise ValueError("approval_timeout_policy must be reject or error")
    if isinstance(queue_size, bool) or not isinstance(queue_size, int) or not 1 <= queue_size <= 65536:
        raise ValueError("queue_size must be an integer from 1 to 65536")
    if model is not None and (not isinstance(model, str) or not model.strip() or len(model) > 100):
        raise ValueError("model must be a non-empty identifier up to 100 characters")
    if reasoning_effort is not None and (not isinstance(reasoning_effort, str) or not reasoning_effort.strip() or len(reasoning_effort) > 32):
        raise ValueError("reasoning_effort must be a non-empty Codex-supported value")
    if output_schema is not None:
        if not isinstance(output_schema, dict) or len(json.dumps(output_schema, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
            raise ValueError("output_schema must be a JSON object below 1 MiB")
    sandbox = SandboxMode(sandbox)
    approval_policy = AppServerApprovalPolicy(approval_policy)
    root = Path(cwd).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("cwd must be an existing directory")
    if sandbox == SandboxMode.FULL_ACCESS and approval_policy != AppServerApprovalPolicy.ON_REQUEST:
        raise ValueError("danger-full-access requires explicit on-request approval policy")
    if network_access is not None and not isinstance(network_access, bool):
        raise ValueError("network_access must be true, false or None")
    if sandbox == SandboxMode.FULL_ACCESS and network_access is not None:
        raise ValueError("app-server danger-full-access does not expose an independent networkAccess setting")
    roots: list[str] = [str(root)]
    seen = {str(root).casefold()}
    for writable_root in writable_roots:
        path = Path(writable_root).expanduser().resolve(strict=True)
        if not path.is_dir() or not path.is_absolute():
            raise ValueError("writable roots must be existing absolute directories")
        if str(path).casefold() in seen:
            raise ValueError("duplicate writable root")
        seen.add(str(path).casefold())
        roots.append(str(path))
    if writable_roots and sandbox != SandboxMode.WORKSPACE_WRITE:
        raise ValueError("writable_roots require workspace-write sandbox")
    conn = AppServerConnection(cwd=root, approval_timeout_seconds=approval_timeout_seconds, approval_timeout_policy=approval_timeout_policy, approval_policy=approval_handling_policy, queue_size=queue_size, registry=registry)
    try:
        conn.request("initialize", {"clientInfo": {"name": "p4-codex-bridge", "title": "P4 Codex Bridge", "version": __version__}}, timeout=30)
        conn.notify("initialized")
        thread = conn.request("thread/start", {
            "cwd": str(root), "model": model, "ephemeral": True,
            "approvalPolicy": approval_policy.value,
            "sandbox": sandbox.value,
        })
        thread_id = thread.get("thread", {}).get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise EventStreamError("app-server thread/start returned no thread ID")
        turn_params: dict[str, Any] = {"threadId": thread_id, "cwd": str(root), "input": [{"type": "text", "text": prompt}]}
        if model:
            turn_params["model"] = model
        if reasoning_effort:
            turn_params["effort"] = reasoning_effort
        if output_schema:
            turn_params["outputSchema"] = output_schema
        if sandbox == SandboxMode.WORKSPACE_WRITE:
            turn_params["sandboxPolicy"] = {"type": "workspaceWrite", "writableRoots": roots, "networkAccess": False if network_access is None else network_access}
        elif sandbox == SandboxMode.READ_ONLY:
            turn_params["sandboxPolicy"] = {"type": "readOnly", "networkAccess": False if network_access is None else network_access}
        else:
            turn_params["sandboxPolicy"] = {"type": "dangerFullAccess"}
        response = conn.request("turn/start", turn_params, timeout=30)
        turn_id = response.get("turn", {}).get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise EventStreamError("app-server turn/start returned no turn ID")
        conn.thread_id = thread_id
        conn.turn_id = turn_id
        conn._state = "RUNNING"
        return CodexTurn(conn, thread_id, turn_id)
    except Exception:
        conn.close()
        raise


def stream_events(prompt: str, **options: Any) -> Iterator[CodexEvent]:
    turn_timeout = options.pop("turn_timeout_seconds", None)
    turn = start_turn(prompt, **options)
    try:
        yield from turn.events(timeout=turn_timeout)
    finally:
        turn.close()
