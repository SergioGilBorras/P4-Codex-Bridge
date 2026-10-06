# App-server events

`CodexBridge.start_turn(prompt, cwd=...)` returns a live `CodexTurn`. Iterate synchronously with `turn.events(timeout=...)`, or use `CodexBridge.stream_events()` / `await bridge.astream_events()` for one-shot consumption. The async surface delegates to the same reader and bounded queues; it does not start a second connection.

Events carry `type`, UTC `timestamp`, `thread_id`, `turn_id`, per-connection `sequence`, normalized `data`, and optional sanitized `raw_event`. Agent message deltas expose `partial_text`; the matching completed agent-message item exposes `final_text`. `turn.final_text` returns the assembled completed text. Empty chunks remain valid events. Interrupted messages retain the partial text and do not synthesize a completed message.

Normalized types include `ThreadStarted`, `ThreadClosed`, `ThreadStatusChanged`, `TokenUsageUpdated`, `TurnStarted`, `AgentMessageDelta`, `AgentMessageCompleted`, `ItemStarted`, `ItemCompleted`, `ToolStarted`, `ToolCompleted`, `ToolFailed`, `ApprovalRequested`, `ApprovalResolved`, `TurnCompleted`, `TurnFailed`, `TurnInterrupted`, `TurnStopped`, `ServerError`, and `UnknownEvent`. Tool classification follows the installed item's `type` field; the Bridge does not infer hidden activity. Unknown methods retain the raw event after redaction and size limiting. Token-usage counters remain numeric; token/auth fields are redacted.

Each subscriber has a bounded queue (default 256). Noncritical event overflow drops that subscriber's event and increments `events_dropped`; critical lifecycle/approval/error events block the protocol reader until the subscriber makes room, applying backpressure instead of dropping them. Consumers should drain or unsubscribe. `stream_all_events()`/`astream_all_events()` multiplex all currently live handles owned by one `CodexBridge` instance. This is not a resident server manager; another process observes persisted lifecycle through `p4-codex events`, but cannot attach to or replay deltas from the live stream.

`get_events(thread_id=..., turn_id=..., after_sequence=...)` replays persisted lifecycle events. It does not replay every delta or tool output. A new live subscription receives events from subscription time only. Abandoning `stream_events()` detaches that iterator without stopping the turn; retrieve the live same-process handle with `get_turn_handle(turn_id)` to subscribe again, interrupt, or close it. Normal terminal completion closes the one-shot helper's app-server process. Explicit interrupt uses `turn.interrupt()`.

App-server notifications use protocol `emittedAtMs` where present; locally synthesized approval/error events use local UTC time. Sequence numbers are local to one app-server connection and do not replace protocol IDs.

See [capability matrix](CAPABILITY_MATRIX.md) for exact protocol names and payload limits.
