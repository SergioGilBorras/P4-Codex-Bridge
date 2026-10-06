# Feature catalog

## Phase 5 additions

| Feature | Status | Notes |
|---|---|---|
| Resident app-server manager | PARTIAL | One owned stdio process, singleton lock, lifecycle methods; Windows daemon/proxy not used |
| Multi-thread registry | PARTIAL | Multiple persistent threads share the manager; app-server thread resume is not yet wired |
| Turn state persistence | PARTIAL | Version-1 SQLite tables and guarded transitions; unknown active turns are not replayed |
| Runtime health and metrics | IMPLEMENTED | Local process/SQLite/counts; no remote or model-health guarantee |
| Crash recovery | PARTIAL | Detects/reports unknown turns; no auto retry or exec process re-adoption |
| Stable run discovery IDs | IMPLEMENTED | `br_...` IDs persisted for exec runs and app-server turns; native IDs resolve when unambiguous |
| `ps` / `inspect` / read-only `watch` | PARTIAL | Exec and runtime manager lifecycle journals; replay is incomplete for unpersisted deltas |
| Attach | NOT_SUPPORTED | No safe, official read-only attach capability established |
| Unified app-server + exec resource scheduling | IMPLEMENTED for managed `start()` submission/dispatch, shared limits, locks and cancellation; PARTIAL for crash recovery | A structurally valid matching result can be reconciled; unverifiable claimed work becomes `LOST` and is never replayed. Direct one-shot `run()` bypasses the scheduler. |

## IMPLEMENTED

- Python `CodexBridge.run()` executes one-shot `codex exec` with JSONL event parsing.
- `CodexBridge.start()` submits an exec run to the persistent shared scheduler, then starts one detached bridge supervisor after an atomic resource claim.
- `list_runs()`, `get_run()`/`status()`, `stop()`, `kill()` and `read_result()` operate only on registered PIDs and check process creation identity before termination.
- Dynamic model discovery through installed app-server `model/list`, including pagination; model catalog does not guarantee entitlement.
- Installed CLI version/capability probes.
- Absolute cwd validation, optional allowed roots, model and timeout validation, Codex sandbox/approval mapping, reasoning effort and JSON-schema output.
- Config policies: isolated/user-ignored, native layered config, and explicit `-c` overrides. User-only config isolation is rejected as unsupported.
- Bounded JSONL/stdout/stderr capture, worker timeout, sanitized result/error output and short-lived schema/output files.
- Python operator CLI: run/start/ps/inspect/watch/status/stop/kill/models/version/capabilities.
- Legacy Node stdin/stdout contract remains available.
- `CodexBridge.start_turn()` starts an ephemeral app-server thread/turn; synchronous and async streams normalize lifecycle, message and tool events. `turn.interrupt()` uses app-server `turn/interrupt`.
- `stream_all_events()` / `astream_all_events()` multiplex all currently live turn handles owned by one `CodexBridge` instance.
- Unknown notifications remain available as sanitized `UnknownEvent`; message deltas assemble into partial and completed text.
- App-server approval requests are manual by default. Python and CLI can approve/reject a live request; default timeout declines it.
- SQLite schema now migrates in-place with lifecycle-event and approval tables. Lifecycle events persist; message deltas and tool output do not.
- CLI adds `events`, `approvals`, `approve`, and `reject`; `ps`/`status` include app-server turn state.
- Event metrics report active streams, pending approvals, received events and dropped noncritical events.
- `CodexBridge.resume()`, `fork()` and `review()` wrap only the installed `codex exec` variants discovered locally. Exec resume/fork are separate from app-server thread lifecycle.
- `output_schema` uses the official `--output-schema` temp-file interface and returns `structured_output`; invalid JSON is reported without repair.
- `capture_last_message` encapsulates `--output-last-message`, reads the bridge-owned temp file, and cleans it on completion, failure and timeout.
- Per-run model, reasoning effort, reasoning summary and verbosity controls use verified CLI/config names; reasoning summary and verbosity use installed schema enums.
- `CodexPermissions` supports exec sandbox/approval policy, validated additional writable roots, and workspace-write network config. Network settings do not govern MCP tools independently.
- `get_effective_config()`, `list_configured_mcps()` and `list_effective_skills()` expose a secret-filtered diagnostic app-server view. They do not claim that a separate `exec` run uses the same config or tools.
- `get_effective_capabilities()` returns machine-readable local discovery plus explicit unknown states for child visibility/effectiveness.

## PARTIAL

- Process recovery: registry can identify a worker that exits without final status as `ORPHANED`; Phase 1 does not reattach to a Codex conversation or restart an interrupted turn.
- Stop: the worker receives a bridge-owned stop request and interrupts the `codex exec` child; it escalates to force kill after the grace period. This is not app-server turn interruption.
- `AUTO_REJECT` and `NEVER_EXPECT_APPROVAL` reject approval requests; `AUTO_APPROVE_SAFE_ONLY` is planned because no deterministic safe-action classifier exists.
- Event subscriptions use bounded per-consumer queues. Noncritical events may be counted and dropped; critical lifecycle/approval/error events backpressure the reader.
- Tool/user-input and MCP elicitation server requests are not handled; the bridge reports them as `ServerError` and replies with unsupported-method error.
- Approval decisions require the owning app-server process to remain live. Persisted lifecycle replay is partial and excludes message deltas.
- Capability probes identify command/help features exposed by the installed version; they do not prove account entitlement, policy access or every effective config layer.
- `exec resume/fork` retain session policy; a caller must explicitly acknowledge that the bridge cannot independently override it. Their result/exit behavior is covered by fake CLI tests only.
- Review supports only installed working-tree/base/commit modes; bridge does not accept arbitrary file lists.
- Diagnostic app-server MCP status may list server/tool descriptors. `callable` remains unknown unless a harmless tool invocation is actually confirmed; no MCP invocation is done by discovery APIs.
- Structured output validates the emitted JSON syntax, not complete compliance with the caller's JSON Schema. Codex/CLI performs schema constrained generation.
- AGENTS/skills/MCP behavior for real exec children is not yet confirmed by a live Phase 4 run. Manual scripts are provided and not executed by default.
- Result text is redacted and stored briefly for asynchronous `start()` runs until `read_result()` consumes it or stale-file cleanup runs after 24 hours.

## PLANNED (later phases)

- Persistent Codex threads/sessions, multiple turns, send/steer, resume/fork and a resident multi-thread app-server manager.
- Full server-request handling, including tool user-input and MCP elicitation.
- Reconnect/replay of protocol deltas; current persistence intentionally captures lifecycle events only.
- Persistent app-server resume/fork/send/steer and a resident manager.
- Fine-grained project/user/explicit MCP and skills policies, only where the supported SDK/protocol can enforce them.
- Planning, implementation, validation and documentation profiles.
- Integrations with P4-Planning-Agent, P4-Jira-Agent-Orchestrator and GestorProyectosIA.

Use [TEST_CATALOG.md](TEST_CATALOG.md) for verification, and [PYTHON_API.md](PYTHON_API.md) for the callable surface.
# Resource scheduling (IMPLEMENTED / PARTIAL)

- IMPLEMENTED: persistent queued payloads, FIFO plus explicit resource priority, atomic SQLite claims, workspace READ/WRITE locks, waiting reasons, queue position, queued cancellation, recovery without replaying claimed work, resources/limits CLI views, runtime metrics and a fake 50-job stress test.
- IMPLEMENTED: app-server and managed exec share global/backend/profile limits, workspace locks, queue state and waiting reasons. Active exec cancel is controlled by the bridge worker; app-server interrupt is routed to its owning runtime manager. Direct one-shot `run()` remains outside this scheduler.
- PARTIAL: exec process adoption after controller loss is unsupported. Runtime limits are configurable via Python, but the CLI does not persist limit changes.
- NOT IMPLEMENTED: business task priority, distributed managers without the local singleton, and isolated worktree sharing.
