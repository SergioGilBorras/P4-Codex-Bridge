# Foreground service

## Current operation

Run the resident app-server manager in the foreground:

```powershell
p4-codex service run --config C:\P4\config\p4-codex.toml
p4-codex service status --config C:\P4\config\p4-codex.toml
p4-codex health --config C:\P4\config\p4-codex.toml
p4-codex metrics --config C:\P4\config\p4-codex.toml --json
p4-codex service stop --config C:\P4\config\p4-codex.toml
p4-codex service restart --config C:\P4\config\p4-codex.toml
p4-codex maintenance status --config C:\P4\config\p4-codex.toml --json
p4-codex maintenance clean --config C:\P4\config\p4-codex.toml --dry-run --json
```

The resident process owns one `CodexRuntimeManager`, its app-server stdio
process, scheduler, SQLite queue, approvals, lifecycle journal and heartbeat.
It starts without stdin input and logs to stderr plus a rotating file. `Ctrl+C`
and Windows `Ctrl+Break` request the same graceful shutdown as the CLI.

The manager's OS advisory lock at `<state_dir>/runs.lock` is the singleton
authority; PID metadata alone is not. Startup acquires it before publishing a
new service state, then opens the registry, starts app-server, runs existing
conservative recovery and enables dispatch. A duplicate process exits without
overwriting the live service record. The lock is released by the OS if the
process dies. Explicitly mismatched process creation identity is treated as
stale; if Windows denies identity inspection, a heartbeat no older than five
seconds is reported as weaker liveness evidence and is never used to kill a PID.

Service state is persisted in the shared `runs.sqlite3`. The local control
channel uses SQLite command rows for status/stop/restart/recover and a separate
typed runtime-command queue for exec submit, thread create and turn start, so no
TCP listener or remote API is opened. Existing `ps`,
`inspect`, `watch`, `resources`, approvals and `cancel` CLI operations read or
write the same registry/journal when given the same state directory. Use
`--state-dir` on a command or set `P4_CODEX_BRIDGE_STATE_DIR` in operator shells.
SQLite IPC is a same-user/local-machine convenience, not strong multi-user
authentication; keep the state directory in the user's private local profile.

## Control-channel decision for 1.0

SQLite is suitable for same-machine status/control and polling the persisted run
journal. Runtime commands use transactional claims, idempotency keys, bounded
payloads, acknowledgements and conservative crash handling. Claimed commands
are not replayed after an ambiguous crash. It has no listener and avoids network
exposure. Windows named pipes could offer an OS-mediated ACL boundary,
but need a separate protocol, client lifecycle and ACL verification; a local
socket has similar platform/version concerns. Neither is justified for the
current status/stop control surface.

The typed command path supports `SUBMIT_EXEC_RUN`, `CREATE_THREAD` and
`START_TURN` through `CodexServiceClient` or JSON-on-stdin CLI commands. It
reuses the existing scheduler, limits, workspace locks and resource policies.
The command table is a request/ack channel, not a second scheduler. It preserves
the pending-payload policy and clears payload content atomically at claim,
retaining only a hash for idempotency. Its cross-process fake-daemon flow is
covered offline. Real Codex service execution remains untested.
never accept arbitrary Python/CLI commands. Do not add HTTP as a shortcut.

`ps`, `inspect`, `watch`, `resources`, health and metrics remain direct
read-only SQLite queries. Cancel/approval decisions and service stop are
explicit state-changing SQLite requests/updates. `CodexServiceClient` is the
public Python facade; consumers do not access schema or registry details.

`service restart` requests clean stop, starts a new Python process detached on
Windows, and waits for a new healthy/degraded heartbeat. Restart of the service
process after a crash is the supervisor's responsibility. There is no internal
unbounded service-process restart loop. App-server restart is separate from
service restart.

## State and shutdown

Service states: `STARTING`, `RECOVERING`, `HEALTHY`, `DEGRADED`, `STOPPING`,
`STOPPED`, `CRASHED`. Since singleton acquisition precedes publication, the
very short pre-lock startup window is not published; clients may see the prior
state until the new manager initializes.

`shutdown_policy = "WAIT"` waits up to the configured timeout for managed active
runs, then requests interruption and closes the owned server. `INTERRUPT`
requests interruption immediately. `FORCE` closes the owned child with a
terminate/kill fallback. It never discovers or kills unrelated Codex PIDs.
Pending approvals are not automatically approved; interrupted/stale decisions
remain subject to the runtime manager's recovery rules.

CLI status includes service/app-server state, versions, queue, active runs,
approvals, workspace locks, DB health, capability snapshot, fatal error and
uptime. Metrics include scheduler and runtime counters; token usage remains
`null` where app-server does not provide it. Missing counters are not estimated.

`maintenance status` performs a dry-run report. `maintenance clean` applies
the configured retention policy unless `--dry-run` is passed. Cleanup only
removes resolved work older than `retention.days` or beyond
`retention.max_completed_runs`; it retains active, queued, waiting, LOST and
unknown work. Resolved events are capped by `retention.max_events_per_run`.
Pending approvals are retained. SQLite integrity, schema markers, size and
pending cleanup are available through `health --json`, `doctor --json` and
`maintenance status --json`. No automatic VACUUM is run.

## Current limitations

- App-server is experimental; startup handshake failure prevents dispatcher
  startup.
- Compatibility APIs classify support from observed capabilities and report
  un-audited newer versions with limitations; this is not a broad guarantee
  against protocol changes.
- Service command requests left CLAIMED at crash are failed as outcome unknown
  and are never replayed automatically.
- Service restart and stop are tested with a fake protocol, not installed as a
  Windows service.
- Runtime MCP filtering is not provided by the installed CLI. Do not treat the
  daemon or OS sandbox as an external-tool allowlist.

Fake human demo (zero tokens):

```powershell
p4-codex service run --fake --state-dir "$env:TEMP\p4-codex-demo"
# In a second terminal:
p4-codex service demo --state-dir "$env:TEMP\p4-codex-demo"
p4-codex ps --state-dir "$env:TEMP\p4-codex-demo"
p4-codex inspect <bridge-run-id> --state-dir "$env:TEMP\p4-codex-demo"
p4-codex watch <bridge-run-id> --follow --state-dir "$env:TEMP\p4-codex-demo"
p4-codex resources --state-dir "$env:TEMP\p4-codex-demo"
p4-codex health --state-dir "$env:TEMP\p4-codex-demo"
p4-codex metrics --state-dir "$env:TEMP\p4-codex-demo"
p4-codex cancel <bridge-run-id> --state-dir "$env:TEMP\p4-codex-demo"
p4-codex service stop --state-dir "$env:TEMP\p4-codex-demo"
```

`service demo` is rejected unless the service reports its fake protocol identity;
the fake server emits delayed local lifecycle events and never starts Codex.
# Cross-process work submission

`CodexServiceClient` is the public same-machine API for sending typed work to a
running foreground service. It uses a dedicated SQLite command table in the
existing state database; callers do not manipulate SQLite or scheduler tables.
The service must already be running. Submission never starts it implicitly.

Supported command types are `SUBMIT_EXEC_RUN`, `CREATE_THREAD`, and
`START_TURN`. Requests are validated typed dataclasses, capped at 1 MiB overall
(512 KiB prompt, 32 KiB metadata), and can carry an idempotency key. A duplicate
key with an identical type and payload returns the same command; reusing the key
for different work is rejected. Claim is transactional and records the service
instance. A command left `CLAIMED` at restart is failed with an unknown-outcome
message and is never automatically replayed; `SUBMITTED` work remains eligible
for claim. This favors at-most-once dispatch over automatic retry in the crash
window.

The service validates workspace roots again. `[codex].allowed_roots` is an
explicit array of existing directories and defaults to the configured service
workspace. Extend it deliberately for other workspaces. Exec submissions route
through the existing `CodexBridge.start()` scheduler; thread creation and turns
route through the resident `CodexRuntimeManager` scheduler. Resource limits,
workspace locks and run IDs remain shared with the existing runtime.

Python callers use `CodexServiceClient` with `ExecRunSubmission`,
`CreateThreadRequest`, or `StartTurnRequest`; CLI clients may send those JSON
objects on stdin using `p4-codex submit exec`, `p4-codex thread create`, and
`p4-codex turn start`. Results acknowledge the command and include native bridge
IDs when available. `wait_command()` uses bounded SQLite polling. The existing
read/control interface remains same-machine and assumes the state directory is
private to the operator account; SQLite is not an authenticated multi-user IPC
boundary.
