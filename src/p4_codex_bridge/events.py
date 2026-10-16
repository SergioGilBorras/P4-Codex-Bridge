from __future__ import annotations

import json
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

from .runtime import redact
from .errors import BridgeError, BridgeTimeoutError


CRITICAL_EVENT_TYPES = {"ApprovalRequested", "ApprovalResolved", "TurnCompleted", "TurnFailed", "TurnInterrupted", "TurnStopped", "ServerError"}
TOOL_ITEM_TYPES = frozenset({
    "commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall",
    "collabAgentToolCall", "webSearch", "imageView", "imageGeneration",
})


def is_tool_item(item: Any) -> bool:
    """Return whether a schema-typed app-server item represents tool activity."""
    return isinstance(item, dict) and item.get("type") in TOOL_ITEM_TYPES


_METHODS = {
    "thread/started": "ThreadStarted",
    "thread/closed": "ThreadClosed",
    "thread/status/changed": "ThreadStatusChanged",
    "thread/tokenUsage/updated": "TokenUsageUpdated",
    "turn/started": "TurnStarted",
    "turn/completed": "TurnCompleted",
    "item/agentMessage/delta": "AgentMessageDelta",
    "item/started": "ToolStarted",
    "item/completed": "ToolCompleted",
    "serverRequest/resolved": "ApprovalResolved",
    "error": "ServerError",
}


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    method: str
    thread_id: str | None
    turn_id: str | None
    item_id: str | None
    action: Any = None
    tool: str | None = None
    arguments: Any = None
    reason: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class CodexEvent:
    type: str
    timestamp: str
    thread_id: str | None = None
    turn_id: str | None = None
    sequence: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    raw_event: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventDecodeError(BridgeError, ValueError):
    """Malformed app-server protocol message."""


class EventStreamError(BridgeError):
    """app-server event transport failed."""


class ApprovalError(BridgeError):
    """Approval could not be resolved."""


class ApprovalTimeoutError(BridgeTimeoutError):
    """An approval remained pending past its configured timeout."""


class ApprovalRejectedError(ApprovalError):
    """The approval was explicitly rejected."""


class ToolEventError(BridgeError):
    """Malformed or failed tool activity event."""


def _safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in list(value.items())[:200]:
            name = str(key)
            clean[name] = "[REDACTED]" if re.search(r"token|secret|password|credential|cookie|api.?key", name, re.IGNORECASE) else _safe(item, depth=depth + 1)
        return clean
    if isinstance(value, list):
        return [_safe(v, depth=depth + 1) for v in value[:200]]
    if isinstance(value, str):
        return redact(value[:10000])
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(str(value))


class EventNormalizer:
    MAX_MESSAGE_CHARS = 4 * 1024 * 1024
    MAX_DELTA_CHARS = 256 * 1024

    def __init__(self) -> None:
        self.sequence = 0
        self._texts: dict[str, list[str]] = {}
        self._text_lengths: dict[str, int] = {}
        self._text_truncated: set[str] = set()
        self._items: dict[str, dict[str, Any]] = {}
        self._text_lock = threading.Lock()
        self._sequence_lock = threading.Lock()

    def next_sequence(self) -> int:
        with self._sequence_lock:
            self.sequence += 1
            return self.sequence

    def normalize(self, message: dict[str, Any]) -> CodexEvent:
        if not isinstance(message, dict):
            raise EventDecodeError("app-server message must be an object")
        method = message.get("method")
        if not isinstance(method, str):
            raise EventDecodeError("app-server message has no method")
        params = message.get("params", {})
        if not isinstance(params, dict):
            raise EventDecodeError("app-server event params must be an object")
        sequence = self.next_sequence()
        event_type = _METHODS.get(method, "UnknownEvent")
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        if method == "item/started":
            event_type = "ToolStarted" if is_tool_item(item) else "ItemStarted"
            if event_type == "ToolStarted":
                with self._text_lock:
                    if len(self._items) >= 4096:
                        self._items.pop(next(iter(self._items)))
                    self._items[str(item.get("id", ""))] = {"started_at_ms": params.get("startedAtMs"), "tool": item.get("type")}
        elif method == "item/completed":
            event_type = "ToolCompleted" if is_tool_item(item) else "ItemCompleted"
            if event_type == "ToolCompleted" and item.get("status") == "failed":
                event_type = "ToolFailed"
        elif method == "turn/completed":
            turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
            status = turn.get("status")
            if status in {"failed", "error"}:
                event_type = "TurnFailed"
            elif status in {"interrupted", "cancelled"}:
                event_type = "TurnInterrupted"
        elif method == "error":
            event_type = "ServerError"
        clean = _safe(params)
        if method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage", {})
            if isinstance(usage, dict):
                allowed = {"cacheWriteInputTokens", "cachedInputTokens", "inputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens", "modelContextWindow"}
                clean["tokenUsage"] = {key: value for key, value in usage.items() if key == "modelContextWindow" and isinstance(value, (int, type(None))) or key == "last" and isinstance(value, dict) or key == "total" and isinstance(value, dict)}
                for bucket in ("last", "total"):
                    if isinstance(clean["tokenUsage"].get(bucket), dict):
                        clean["tokenUsage"][bucket] = {key: value for key, value in clean["tokenUsage"][bucket].items() if key in allowed and isinstance(value, (int, type(None)))}
        if method == "item/agentMessage/delta":
            item_id = str(params.get("itemId", ""))
            delta = params.get("delta", "")
            if not isinstance(delta, str):
                raise EventDecodeError("agent message delta must be text")
            delta = delta[: self.MAX_DELTA_CHARS]
            with self._text_lock:
                room = max(0, self.MAX_MESSAGE_CHARS - self._text_lengths.get(item_id, 0))
                bounded = delta[:room]
                self._texts.setdefault(item_id, []).append(bounded)
                self._text_lengths[item_id] = self._text_lengths.get(item_id, 0) + len(bounded)
                if len(bounded) != len(params.get("delta", "")):
                    self._text_truncated.add(item_id)
                clean["partial_text"] = redact("".join(self._texts[item_id]))
                if item_id in self._text_truncated:
                    clean["text_truncated"] = True
        if event_type in {"AgentMessageCompleted", "ItemCompleted"} and item.get("type") == "agentMessage":
            item_id = str(item.get("id", ""))
            with self._text_lock:
                assembled = "".join(self._texts.pop(item_id, []))
                if not assembled and isinstance(item.get("text"), str):
                    assembled = item["text"][: self.MAX_MESSAGE_CHARS]
                clean["final_text"] = redact(assembled)
                if item_id in self._text_truncated:
                    clean["text_truncated"] = True
                self._text_lengths.pop(item_id, None)
                self._text_truncated.discard(item_id)
            event_type = "AgentMessageCompleted"
        if event_type in {"ToolCompleted", "ToolFailed"}:
            with self._text_lock:
                started = self._items.pop(str(item.get("id", "")), {})
            started_at = started.get("started_at_ms")
            completed_at = params.get("completedAtMs")
            if isinstance(started_at, (int, float)) and isinstance(completed_at, (int, float)):
                clean["duration_ms"] = max(0, completed_at - started_at)
            clean["tool"] = item.get("type")
            clean["result_summary"] = str(item.get("output") or item.get("aggregatedOutput") or item.get("status") or "")[:1000]
            if event_type == "ToolFailed":
                clean["error"] = clean["result_summary"]
        data = {"method": method, **clean}
        thread = params.get("thread") if isinstance(params.get("thread"), dict) else {}
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        return CodexEvent(
            type=event_type,
            timestamp=datetime.fromtimestamp(message.get("emittedAtMs", time.time() * 1000) / 1000, timezone.utc).isoformat(),
            thread_id=params.get("threadId") or thread.get("id"),
            turn_id=params.get("turnId") or turn.get("id"),
            sequence=sequence,
            data=data,
            raw_event=_safe(message),
        )


class EventSubscription:
    """Bounded per-subscriber queue. Noncritical deltas may be dropped; critical events block."""

    def __init__(self, *, maxsize: int = 256, thread_id: str | None = None, turn_id: str | None = None):
        self.queue: queue.Queue[CodexEvent | BaseException | None] = queue.Queue(maxsize=maxsize)
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.dropped = 0
        self.closed = False

    def publish(self, event: CodexEvent) -> None:
        if self.closed or (self.thread_id and event.thread_id != self.thread_id) or (self.turn_id and event.turn_id != self.turn_id):
            return
        if event.type not in CRITICAL_EVENT_TYPES:
            try:
                self.queue.put_nowait(event)
            except queue.Full:
                self.dropped += 1
            return
        while not self.closed:
            try:
                self.queue.put(event, timeout=0.1)
                return
            except queue.Full:
                continue

    def __iter__(self) -> Iterator[CodexEvent]:
        while True:
            try:
                item = self.queue.get(timeout=0.25)
            except queue.Empty:
                if self.closed:
                    return
                continue
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    def close(self) -> None:
        self.closed = True
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            # The subscription is closed; consumers may drain remaining events before exit.
            pass


def decode_json_line(line: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, TypeError) as exc:
        raise EventDecodeError("malformed app-server JSON message") from exc
    if not isinstance(value, dict):
        raise EventDecodeError("app-server JSON message must be an object")
    return value
