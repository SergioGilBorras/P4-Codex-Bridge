# Live run discovery and observation

## IDs and metadata

Every exec run and app-server turn receives a `bridge_run_id` (`br_<12 hex>`)
before provider work starts. Native exec session IDs, app-server thread/turn IDs,
server/PID identity, backend, cwd, model, profile, permissions and sanitized
agent/task metadata are persisted where that backend supplies them. To discover
an active run, use `p4-codex ps --active`; consumers can pass metadata such as
`agent_name`, `agent_role`, `task_key`, `project`, and `workspace` without the
bridge interpreting its business meaning.

The CLI, `CodexBridge`, and `CodexRuntimeManager` use the same default
`runs.sqlite3`. Set `P4_CODEX_BRIDGE_STATE_DIR` in both processes to a shared
state directory when they run under different service accounts/configurations.

## Commands

```powershell
p4-codex ps --active --task P4-123
p4-codex ps --agent RequirementAnalysisAgent --json
p4-codex inspect br_0123456789ab
p4-codex watch br_0123456789ab --follow
p4-codex watch --task P4-123 --follow
```

`ps` is discovery, `inspect` is a point-in-time snapshot, and `watch` is read-only.
Watch may display sanitized assistant messages, tool lifecycle, approvals and errors.
Use `--no-deltas`, `--no-tools`, `--no-approvals`, `--since` and `--json` to control presentation.
Multiple watchers poll the shared SQLite journal independently; closing one does not signal Codex.
Selectors matching zero or multiple active runs fail with candidate IDs instead of choosing one.

Exec streams record `thread.started`, completed assistant messages, and tool item lifecycle
from Codex JSONL. App-server runs record lifecycle, message deltas and tool events received by
the manager. SQLite retains bounded, sanitized event payloads. After restart, persisted events
can be inspected, but message replay is incomplete whenever the backend did not persist deltas;
the inspection field `event_replay_complete` is therefore false.

The Python API is `CodexBridge.list_runs(...)`, `resolve_run_reference(id)`, `inspect(id)`,
`watch(...)`, and `awatch(...)`. `announce_run=True` sends sanitized announcements through the
`p4_codex_bridge.announce` logger; Python does not print to stdout. The CLI's `--announce` writes
announcements to stderr so stdout remains machine-readable.

`attach` is not implemented. Codex's `exec resume` and app-server thread resume are work operations
that can change the conversation; neither is treated as an interactive, read-only attach. No
attach capability is claimed.
# Scheduler visibility

`ps` includes workspace, access mode, queue position and waiting reason when scheduler metadata exists. `inspect` includes the blocker and resource dimensions. `watch` journals scheduling state and resource acquisition/release events. `resources` reports global/backend/profile slots and workspace locks.
