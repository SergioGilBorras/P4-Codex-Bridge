# Feature catalog

## 1.0 software closeout changes

- Python is the only canonical implementation; the in-repository JavaScript
  runtime and npm workflow were removed (ADR-002).
- `RunSecurityPolicy` validates trust, project context and unfiltered external
  MCP risk before direct/managed/service execution paths. Requested MCP
  isolation and unknown effective MCP state are rejected because the bridge
  has no run-specific proof that the child MCP set is empty. An acknowledged
  TRUSTED opt-in permits unfiltered risk with a warning, not an isolation
  guarantee.
- App-server RPC operations use an explicit capability-to-method map. Generated
  schema support is limited until an actual successful runtime RPC confirms the
  method. UNKNOWN is distinct from UNSUPPORTED and is rejected for required
  operations. The installed package/version and schema generator are identified;
  generated local schema was verified on 2026-10-07 (Codex CLI 0.160.1; 262
  methods; SHA-256 `4a02439823bc98fbbca86d9f934d5a90a638b41ec16c635c8c4448b2b9e14867`).
  The normal sandbox invocation had an environment `EPERM`; schema generation
  completed with local filesystem access. Runtime support still requires
  handshake/RPC evidence.
- The package root uses an explicit export allowlist and regression test.
  Runtime manager, scheduler, registry, SQLite and service implementation types
  are not package-root exports.
- CLI command tree, JSON/JSONL output rules and exit codes are frozen and covered
  by contract tests. Root `--help` and `--version` remain informational text.
- Strict TOML key names and bridge environment variables are frozen; unknown
  keys fail. No `config_version` field is used.
- Per-run MCP filtering remains NOT_SUPPORTED / a documented known limitation.
  The typed gate rejects unknown MCP state, requested isolation and untrusted
  risk by default. A trusted explicit external-side-effect acknowledgement
  permits unfiltered risk with a warning; this is not isolation.

## Phase 5 and Phase 6 runtime additions

The table below is maintained as a release catalog; rows superseded by the 1.0
software closeout reflect the current 1.0 behavior described in the notes.

| Feature | Status | Notes |
|---|---|---|
| Resident app-server manager | PARTIAL | One owned stdio process, singleton lock, lifecycle methods; Windows daemon/proxy not used |
| Multi-thread registry | IMPLEMENTED | Persistent threads share one manager; resume and native fork are exposed |
| Turn state persistence | PARTIAL | Version-2 SQLite metadata; matching remote terminal turns reconcile, active turns are not adopted |
| Runtime health and metrics | IMPLEMENTED | Local process/SQLite/counts; no remote or model-health guarantee |
| Crash recovery | PARTIAL | Detects/reports unknown turns; no auto retry or exec process re-adoption |
| Stable run discovery IDs | IMPLEMENTED | `br_...` IDs persisted for exec runs and app-server turns; native IDs resolve when unambiguous |
| `ps` / `inspect` / read-only `watch` | PARTIAL | Exec and runtime manager lifecycle journals; replay is incomplete for unpersisted deltas |
| Attach | NOT_SUPPORTED | No safe, official read-only attach capability established |
| Unified app-server + exec resource scheduling | IMPLEMENTED for managed `start()` submission/dispatch, shared limits, locks and cancellation; PARTIAL for crash recovery | A structurally valid matching result can be reconciled; unverifiable claimed work becomes `LOST` and is never replayed. Direct one-shot `run()` bypasses the scheduler. |
| Runtime approvals | IMPLEMENTED | Central JSON-RPC reader, owner-bound persisted decision, Python and shared CLI API, timeout decline; restart marks pending requests stale |
| Thread resume/fork | IMPLEMENTED | `thread/resume` and `thread/fork` calls use installed app-server protocol; fork records parent and optional history cutoff |
| Turn steer | IMPLEMENTED | `turn/steer` requires exact active `expectedTurnId`; not an alias for a new turn |
| Turn recovery | PARTIAL | `thread/turns/list` reconciles matching terminal states from one page (100); no active turn adoption or replay |
| Reconnection/replay | PARTIAL | Explicit `restart()` restarts transport; lifecycle replay is local only, deltas are not replayed |

## Service and daemon hardening

| Feature | Status | Notes |
|---|---|---|
| Foreground resident service | IMPLEMENTED | Owns one runtime manager and shared registry until a controlled shutdown; app-server remains experimental |
| Local singleton | IMPLEMENTED | Existing OS advisory lock is the authority; service heartbeat/identity is diagnostic and duplicate start is rejected |
| Service status, health and metrics | IMPLEMENTED | Read sanitized SQLite snapshots from another CLI process; fields unavailable from Codex remain null/absent |
| Local service control | IMPLEMENTED | SQLite command queue for stop/restart/recover and fake-only demo; same-user state directory is the trust boundary |
| TOML service config | IMPLEMENTED | Typed allowlisted fields, validation and CLI/environment/file/default precedence; no secrets |
| Graceful shutdown | IMPLEMENTED | WAIT, INTERRUPT and FORCE policies; owned child only, with timeout/termination fallback |
| Startup recovery | PARTIAL | Existing conservative registry/scheduler recovery runs before dispatch; uncertain claimed work is not replayed |
| Rotating operational logs | IMPLEMENTED | Bounded rotating file plus stderr; human or JSON format; prompts and environment are excluded |
| Windows SCM service wrapper | PLANNED | Foreground operation is supported; Task Scheduler/WinSW/NSSM guidance only, no wrapper is installed |
| Cross-process turn submission | IMPLEMENTED | Typed `CodexServiceClient` and CLI requests support thread creation and turn start through the daemon; the service revalidates requests. |
| Retention/maintenance | IMPLEMENTED | Explicit `maintenance clean` applies configured retention; cleanup is not automatic at startup and does not run VACUUM. |
| Fake resident operator demo | IMPLEMENTED | `service run --fake` plus `service demo`; fake protocol only, zero Codex calls |

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
- The former Node stdin/stdout contract is retained only as historical documentation in `docs/CONTRACT.md`; its runtime was removed before 1.0.0 (ADR-002).
- `CodexBridge.start_turn()` starts an ephemeral app-server thread/turn; synchronous and async streams normalize lifecycle, message and tool events. `turn.interrupt()` uses app-server `turn/interrupt`.
- `stream_all_events()` / `astream_all_events()` multiplex all currently live turn handles owned by one `CodexBridge` instance.
- Unknown notifications remain available as sanitized `UnknownEvent`; message deltas assemble into partial and completed text.
- App-server approval requests are manual by default. Python and CLI can approve/reject a live request; default timeout declines it.
- `CodexRuntimeManager` exposes `resume_thread`, `fork_thread`, `steer_turn`, `list_pending_approvals`, `get_approval`, `approve`, and `reject`.
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
- AGENTS/skills/MCP behavior for a real exec child remains NOT_CONFIRMED. Phase 7 performed zero model turns; see the host/child distinctions and safety limitation in `docs/MCP.md`, `docs/SKILLS.md`, and `docs/AGENTS_BEHAVIOR.md`.
- Result text is redacted and stored briefly for asynchronous `start()` runs until `read_result()` consumes it or stale-file cleanup runs after 24 hours.

## Phase 7: MCP / skills / AGENTS effective behavior

| Feature | Status | Notes |
|---|---|---|
| MCP session/CLI/app-server inventory distinction | IMPLEMENTED as documented discovery | Current session counts are snapshots; `codex mcp list` and app-server diagnostic were recorded separately. |
| Diagnostic MCP server/tool listing | IMPLEMENTED | `list_configured_mcps()` reports descriptors; it does not call tools or prove per-run effectiveness. |
| Diagnostic skills listing | IMPLEMENTED | `list_effective_skills()` uses `skills/list`; current diagnostic child returned five enabled system entries. |
| Combined `get_effective_capabilities(include_diagnostics=True)` | IMPLEMENTED | Adds filtered config/MCP/skills diagnostics; preserves unknown `exec` and host-session states. `isolated` is explicitly unsupported for app-server diagnostics. |
| OpenAI Docs MCP callability | REAL_TESTED in host development session | One harmless docs query succeeded. Not a runtime dependency and not a child-run proof. |
| AGENTS behavior per policy/cwd | NOT_CONFIRMED | Marker smoke is available but no inference ran because the external MCP surface cannot be bounded per run. |
| Child skill selection/effectiveness | NOT_CONFIRMED | Descriptor listing is not a selection receipt; no inference smoke ran. |
| Child MCP invocation/effectiveness | NOT_CONFIRMED | Apps/read/write operations were not called; no matching `exec` run was observed. |
| Per-run MCP allow/deny policy | NOT_SUPPORTED by observed CLI surface; enforcement PARTIAL | No allowlist flag was found. Do not imply a profile can filter arbitrary MCP tools. |
| External side-effect security gate | PARTIAL | Typed trust/risk policy rejects unacknowledged or untrusted external MCP use and requested MCP isolation; explicitly acknowledged trusted use is warned. Codex still supplies no per-run filter, so prevention is not guaranteed. |

## PLANNED (later phases)

- Full server-request handling, including tool user-input and MCP elicitation.
- Automatic reconnect, active-turn adoption, and replay of remote protocol deltas; current persistence intentionally captures lifecycle events only.
- Fine-grained project/user/explicit MCP and skills policies, only where the supported SDK/protocol can enforce them.
- Planning, implementation, validation and documentation profiles.
- Integrations with P4-Planning-Agent, P4-Jira-Agent-Orchestrator and GestorProyectosIA.

Use [TEST_CATALOG.md](TEST_CATALOG.md) for verification, and [PYTHON_API.md](PYTHON_API.md) for the callable surface.
# Resource scheduling (IMPLEMENTED / PARTIAL)

- IMPLEMENTED: persistent queued payloads, FIFO plus explicit resource priority, atomic SQLite claims, workspace READ/WRITE locks, waiting reasons, queue position, queued cancellation, recovery without replaying claimed work, resources/limits CLI views, runtime metrics and a fake 50-job stress test.
- IMPLEMENTED: app-server and managed exec share global/backend/profile limits, workspace locks, queue state and waiting reasons. Active exec cancel is controlled by the bridge worker; app-server interrupt is routed to its owning runtime manager. Direct one-shot `run()` remains outside this scheduler.
- PARTIAL: exec process adoption after controller loss is unsupported. Runtime limits are configurable via Python, but the CLI does not persist limit changes.
- NOT IMPLEMENTED: business task priority, distributed managers without the local singleton, and isolated worktree sharing.
