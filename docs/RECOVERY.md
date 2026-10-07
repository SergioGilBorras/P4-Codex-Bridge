# Runtime recovery

`CodexRuntimeManager` owns one stdio `codex app-server` child, identified in its
registry by bridge instance ID, PID, command fingerprint and start time. The OS
lock is advisory and released by the OS after owner exit; PID metadata alone is
never used to terminate another process. Only the direct `Popen` child is stopped.

Threads are persistent (`ephemeral: false`). The manager restores their local
metadata on startup with `recovered=true` and `remote_state_verified=false`.
`resume_thread(thread_id)` calls the installed `thread/resume` method and
verifies the returned ID. It does not restart a turn. Ephemeral forked threads
are marked non-resumable.

After a successful thread resume, the manager queries `thread/turns/list` with
a page limit of 100. A matching local turn ID with remote status `completed`,
`failed`, or `interrupted` can reconcile the conservative local `LOST` marker.
An `inProgress` result is reported but is not re-adopted or resumed. Missing
IDs, older history outside the page, transport errors, or incompatible server
state remain UNKNOWN/LOST. No prompt is automatically replayed.

Outstanding approvals are bound to `server_id`, bridge run, thread and turn.
After manager restart, approvals owned by the former server become
`STALE_LOCAL`; the bridge neither approves nor rejects them during recovery.
Approvals are answered only by the manager that still owns the original JSON-RPC
request. Approval timeout is a separate setting and sends `decline`.

SQLite schema version 2 adds persistent thread parent/ephemeral/recovery metadata
and runtime approval ownership. Version 1 migrates additively; unknown schema
versions fail closed. Sanitized lifecycle and approval events are journaled;
resident-manager message deltas and tool payloads are not persisted. Replay is
local lifecycle replay only, never remote delta replay.

The current runtime owns a single local manager lock and a single app-server
reader. `restart()` recreates the transport, but no background reconnect loop,
remote event replay, active-turn adoption, or Windows daemon/proxy mode is
implemented. A caller explicitly resumes persistent threads after restart.

## Foreground service

`p4-codex service run` owns this same runtime singleton and invokes its startup
recovery before publishing healthy status. A stale service heartbeat is
reported as `CRASHED`; the OS advisory lock is released by process death. Queue
recovery stays conservative: unclaimed rows may be restored, while uncertain
claimed work is marked unknown/lost and is not re-executed. `service restart`
is an explicit new-process operation. Automatic restart of the service process
is delegated to a supervisor; no internal infinite restart loop exists. See
[service](SERVICE.md) and [Windows guidance](WINDOWS_SERVICE.md).

## Recovery scenario audit

| Failure / prior state | Classification | Policy |
|---|---|---|
| app-server child crash | RECONCILED | Crash is recorded; turns are not replayed |
| foreground service crash | RECONCILED | OS releases singleton; next start checks identity/heartbeat and runs conservative recovery |
| runtime-manager crash | RECONCILED | Registry is reopened; uncertain active work is not adopted |
| exec worker/controller dies while child may live | UNKNOWN | No safe stdio/result readoption protocol; do not signal/reexecute based on PID alone |
| exec child no longer exists | LOST | Reconcile from process identity evidence; no retry |
| remote thread exists | RECOVERED after explicit resume | `thread/resume` verifies native ID; there is no automatic reconnect |
| remote turn is terminal and appears in listed history | RECONCILED | Explicit resume can record terminal state; only one page up to 100 turns is checked |
| remote turn reports `inProgress` | UNKNOWN | Not adopted; no duplicate turn starts |
| approval pending after owner-server loss | LOST / STALE_LOCAL | Never auto-approve or auto-reject during recovery |
| workspace lock owner is stale | RECONCILED when identity/run evidence permits | Unknown ownership is retained for operator review |
| queue claim interrupted before native ID persistence | LOST / UNKNOWN | Claim is not dispatched twice; manual review required |
| watcher disconnect/reconnect | RECOVERED partially | Read persisted lifecycle journal; message/tool deltas may be absent |

No recovery path claims success from a PID alone or repeats a prompt without
evidence. Exec child readoption and app-server transport reconnection are
NOT_SUPPORTED by the current design.
# Service command recovery

Unclaimed `SUBMITTED` command rows survive a service restart and can be claimed
by the next healthy instance. A `CLAIMED` row without an acknowledgement is
marked `FAILED` with outcome unknown. It is not replayed because the bridge may
already have created a thread, run or turn before the crash. Clients use their
idempotency key to retrieve an existing command result; the service does not
infer that an unknown command is safe to retry.
