# Lifecycle and recovery

## Run discovery

Each exec and app-server run is assigned a `br_...` bridge ID before work starts.
Native session/thread/turn identifiers are additional lookup keys. `inspect`
resolves exactly one run; ambiguous native identifiers fail. `watch` polls the
persisted event journals read-only and does not hold or control the provider
stream. See [live observability](LIVE_OBSERVABILITY.md).

## Resident manager (Phase 5)

`CodexRuntimeManager` owns a single stdio app-server process, one JSON-RPC
reader, and a local SQLite registry. Threads persist independently of turns.
Startup is idempotent for the same object and a lock prevents a second local
manager using the same lock path. Graceful shutdown closes stdin and waits,
then terminates/kills only the owned direct child as fallback. `INTERRUPT`
requests interruption for active turns before closing; `FORCE` shortens the
wait. A bridge/server crash leaves in-flight outcomes `UNKNOWN`; it never
silently reruns them. See [recovery](RECOVERY.md).

## Phase 1: one-shot exec

Managed `start()` persists a stable `br_...` ID and queue payload, claims shared capacity/workspace resources atomically, then launches a detached bridge worker that starts exactly one `codex exec` child in the validated cwd. Direct `run()` remains one-shot and bypasses resource scheduling. The worker enforces its turn timeout, drains bounded output, sanitizes the result, and records terminal status. Prompts are sent through a pipe; pending managed payload is deleted on claim or cancellation.

```text
STARTING -> RUNNING -> COMPLETED | FAILED | TIMED_OUT | STOPPED
```

`stop()` requests cooperative cancellation and escalates to identity-verified process-tree termination after its grace period. `kill()` is immediate. Only PIDs registered by this bridge can be managed. A worker that exits without a terminal row becomes `ORPHANED`; Phase 1 cannot reattach to a Codex conversation.

## Phase 3: app-server one-turn lifecycle

`start_turn()` spawns one `codex app-server --listen stdio://` process, initializes it, starts an ephemeral `thread/start`, then submits one `turn/start`. A single reader thread demultiplexes JSON-RPC replies, notifications, and server-initiated requests. Notifications are normalized and distributed to bounded subscriptions. `turn.interrupt()` calls `turn/interrupt`; `turn.close()` closes the bridge-owned app-server process.

```text
STARTING -> RUNNING <-> WAITING_APPROVAL -> COMPLETED | FAILED | INTERRUPTED
```

Approval requests are held pending. Manual `approve`/`reject` decisions can be submitted through Python or the CLI; a registry watcher in the owning app-server process sends the protocol response. An explicit `AUTO_REJECT`/`NEVER_EXPECT_APPROVAL` policy declines requests. The separate approval timeout declines; turn/event iteration timeout interrupts before the generator closes the server. JSON-RPC requests have their own response timeout.

`p4-codex ps` derives live and historical app-server turn states from SQLite lifecycle events and pending approvals. `status(turn_id)` and `get_turn_status(turn_id)` use the same state. `WAITING_APPROVAL` is derived from a pending approval record. Lifecycle events are persisted in SQLite; message deltas and tool output are not persisted.

### Stream disconnect and replay

Closing a subscription does not stop the turn; closing the `CodexTurn` or its one-shot `stream_events()` context closes the owned app-server process. A same-process caller may subscribe to an existing live handle. A separate process can read persisted lifecycle events with `p4-codex events <turn>`, but cannot attach to an in-memory stream or recover deltas. `events --follow` polls the lifecycle table; it is not upstream event replay. Critical queue events are never silently dropped: reader backpressure blocks; noncritical overflow is counted per subscriber.

The Bridge does not claim durable session recovery. The Codex thread is created ephemeral for this phase, and no resume identifier is promised after close or consumer/bridge restart. An approval decision is only actionable while the owning app-server connection remains live.

## Phase 5 plan

- Evaluate official `openai-codex` SDK versus the current narrow JSON-RPC transport for lifecycle stability and deployment version pinning.
- Expose persistent thread start/resume/fork, send/steer, session lookup, and multi-turn state.
- Add a resident manager only if concurrency justifies it. Namespace ownership and stop only app-server processes started by the Bridge.
- Design recovery for bridge/consumer/app-server crash before claiming resume. Persist minimal thread IDs, process identity and lifecycle state; do not duplicate Orchestrator task ownership.
- Add recovery/reconnection, a resident multi-session manager, health/observability and version compatibility gates.
- Revisit exec/app-server capability parity as local schemas evolve.

## Recovery limits

- `exec` worker crash: mark run `ORPHANED`; do not automatically rerun prompt.
- app-server crash: report stream failure and retain only lifecycle events already committed to SQLite; no delta replay or turn restart.
- consumer disconnect: app-server may continue while the `CodexTurn` owner remains alive; another process can observe DB lifecycle only.
- orphan child/server: terminate only the exact process identity recorded/owned; never kill by process name.
- event data stored/replayed: sanitized critical lifecycle and approval events only. No prompt, token, tool transcript, or complete event replay.
# Scheduled run states

Runtime work moves through `SUBMITTED → QUEUED → WAITING_FOR_SLOT/RUNNING`, then completion, failure, interruption, cancellation or loss. A queued cancellation never starts Codex. A claimed run found after manager restart is marked `LOST`; it is not replayed without evidence that replay is safe. Resource-slot and workspace-lock details are in [RESOURCE_SCHEDULER.md](RESOURCE_SCHEDULER.md).
