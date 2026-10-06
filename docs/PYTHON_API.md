# Python API

## Public surface and stability

Consumers should import only from `p4_codex_bridge`. The supported consumer
facade is `CodexBridge`; `RuntimeLimits` and the typed request/result/status,
permission and public error models are stable contracts. `CodexRuntimeManager`
and its returned `ManagedThread` / `ManagedTurn` handles are experimental while
the resident lifecycle and recovery contract is being stabilized.

| Component | Classification | Consumer guidance |
|---|---|---|
| `CodexBridge` | STABLE for one-shot exec, managed scheduled `start`, discovery and observation; app-server lifecycle remains EXPERIMENTAL | Preferred consumer entry point. |
| `CodexRuntimeManager` | EXPERIMENTAL | Use only where app-server threads and turns are explicitly needed. |
| `RuntimeLimits` | STABLE configuration model | Resource caps; changes do not preempt active work. |
| scheduler / `ResourceScheduler` | INTERNAL | SQLite queue implementation; do not import it from consumers. |
| registry / SQLite schema | INTERNAL | Persistence implementation can migrate without consumer changes. |
| app-server transport and process helpers | INTERNAL | Protocol and OS process details are not public contracts. |
| Node compatibility bridge | EXPERIMENTAL compatibility surface | Kept for migration; Python is the primary API. |

The public package exports only facade types and value/error models. It does
not export the scheduler, registry, canonicalization helper, transport, or
process functions. Internal modules may change between minor releases.

### Method-level status

For `CodexBridge`, STABLE methods are `get_version`, `get_capabilities`,
`list_models`, `get_effective_config`, `list_configured_mcps`,
`list_effective_skills`, `get_effective_capabilities`, `start`, `run`,
`resume`, `fork`, `review`, `get_run`, `status`, `list_runs`,
`resolve_run_reference`, `inspect`, `watch`, `awatch`, `format_run_announcement`,
`stop`, `kill`, and `read_result`.

EXPERIMENTAL methods are `start_turn`, `stream_events`, `astream_events`,
`stream_all_events`, `astream_all_events`, `get_turn_handle`,
`get_turn_status`, `list_pending_approvals`, `approve`, `reject`,
`get_event_metrics`, `get_events`, and `list_managed`; they depend on the
experimental app-server protocol and local lifecycle journal. Methods whose
names start with `_` are INTERNAL. No method is currently marked DEPRECATED.
`CodexBridge.start` is the managed asynchronous `exec` submission API and uses
the persistent shared resource queue. `CodexBridge.run` remains direct one-shot
execution and does not wait in that queue. `CodexBridge.cancel` is the shared
cancel entry point; active app-server cancellation is delivered to the owning
runtime manager through the local SQLite control-request table.
`CodexBridge.recover_exec_runs()` reconciles owned worker identities and accepts
only a structurally valid result file matching the bridge run ID. It marks
unverifiable claimed work `LOST`; it never restarts a Codex turn.

All `CodexRuntimeManager` lifecycle, scheduling, metrics, health, recovery,
thread, turn and cancel methods are EXPERIMENTAL. `CodexTurn` is an EXPERIMENTAL
returned handle. `ResourceScheduler`, `RunRegistry`, `AppServerConnection`,
SQLite schema helpers and `_worker` process functions are INTERNAL. Consumers
should not use them as a substitute for a missing facade operation.

### `CodexBridge` methods

Stable: `get_version`, `get_capabilities`, `list_models`, `run`, `start`,
`get_run`, `status`, `list_runs`, `resolve_run_reference`, `inspect`, `watch`,
`awatch`, `stop`, `kill`, `read_result`, `resume`, `fork`, `review`,
`start_turn`, `stream_events`, `astream_events`, `stream_all_events`,
`astream_all_events`, `get_events`, `approve`, `reject`,
`get_effective_config`, `list_configured_mcps`, `list_effective_skills`, and
`get_effective_capabilities` as individually described below. App-server
diagnostics and child visibility remain partial or unknown where stated; the
method being public does not strengthen its evidence.

Experimental: turn subscriptions/multiplexing and direct approval/event
handling APIs, because they depend on the installed app-server protocol.

`start()` is the managed/scheduled `exec` path; `run()` deliberately retains
the direct one-shot path. App-server turns and scheduled exec runs share the
same global/backend/profile limits and workspace locks. `cancel()` cancels
queued jobs before launch, signals managed exec workers with an identity-checked
termination fallback, and routes app-server interruption to its owner. The
backends keep their native lifecycle semantics and are not interchangeable.

### Lifecycle verbs

`cancel` means withdraw a submitted job before it starts. `interrupt` asks an
active app-server turn to stop while retaining its thread when supported.
`stop` requests cooperative termination of a managed exec run. `kill` is the
identity-checked OS process-tree fallback. These operations are not aliases;
the current CLI does not provide unified active-run cancellation across both
backends.

### Errors and resource scheduling boundary

The package defines `BridgeError`, `ConfigurationError`,
`CapabilityUnavailableError`, `QueueFullError`, `ResourceUnavailableError`,
`RunNotFoundError`, `RunStateError`, `BackendError`, `AuthenticationError`,
`ProtocolError`, and `BridgeTimeoutError`. `QueueFullError` is raised by the
internal persistent scheduler. Error normalization across all legacy facade
methods is still PARTIAL; some methods preserve `ValueError`, `KeyError`, or
backend-specific failures for compatibility.

## Resident runtime (Phase 5)

`CodexRuntimeManager(cwd=..., database_path=...)` owns one app-server child.
Call `start()`, `health()`, `create_thread(...)`, `start_turn(thread_id,
prompt)`, `list_threads()`, `list_turns()`, `get_metrics()`, `recover()` and
`stop(mode="WAIT" | "INTERRUPT" | "FORCE")`. It supports context-manager use.
Turn submissions pass through the persistent app-server resource queue and
return a handle while queued. The default active-turn limit is conservative.
The manager is experimental; `CodexBridge.start_turn()` remains an ephemeral
connection path; managed `CodexBridge.start()` exec workers use the shared queue.
Full cancellation/recovery parity is not provided.

## Discovery and watch

`CodexBridge.start/run(..., metadata={...})` and `start_turn(..., metadata=...)`
accept bounded, redacted operational metadata. `announce_run=True` writes only
sanitized announcements to the configured logger. Use `list_runs(active=...,
task=..., agent=..., backend=..., status=...)`, `resolve_run_reference(id)`,
`inspect(id)`, `watch(id, follow=...)` or `awatch(...)`. `watch` is read-only and
independently polls persisted events. See [live observability](LIVE_OBSERVABILITY.md).

## Install / import

The package has no third-party runtime dependency in Phase 1. Version `0.3.0` is defined once in `p4_codex_bridge.__version__` and read dynamically by setuptools and `p4-codex --version`. Install this repository into the caller's Python environment with `pip install -e .`, or add the repository to that environment's import path. Codex CLI remains an external installed prerequisite. Python >=3.10 is declared.

```python
from p4_codex_bridge import (
    ApprovalPolicy,
    CodexBridge,
    CodexPermissions,
    SandboxMode,
)

bridge = CodexBridge(allowed_roots=[r"F:\ProyectosPYCHARM\PythonProject"])
result = bridge.run(
    "Explain the main flow in three bullets",
    cwd=r"F:\ProyectosPYCHARM\PythonProject\P4",
    profile="analysis",
    model=None,
    timeout_seconds=300,
    permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
)
if not result.ok:
    raise RuntimeError(result.error)
print(result.content)
```

## Public methods

| Method | Behavior |
|---|---|
| `get_version()` | Executes `codex --version` and returns its first line. |
| `get_capabilities()` | Queries local root, `exec`, advanced exec subcommands, and `app-server` help; returns machine-readable support/state notes. |
| `list_models(include_hidden=False)` | Uses short-lived app-server JSON-RPC `model/list`, paginated. Catalog is not an entitlement check. |
| `run(prompt, ...)` | Starts an asynchronous managed one-shot run, waits, returns `RunResult`, consumes the result file. |
| `start(prompt, ...)` | Starts one bridge-managed `codex exec` process and returns `BridgeRun`; it does not create a persistent Codex conversation. |
| `get_run(id)` / `status(id)` | Returns current managed-process metadata; dead workers without a terminal update become `ORPHANED`. |
| `list_runs()` | Lists only records in this bridge's local registry. |
| `stop(id)` | Requests cooperative cancellation through the worker; falls back to `kill()` after its grace interval. |
| `kill(id)` | Force terminates only identity-verified PIDs registered for that run. |
| `read_result(id)` | Reads and deletes the sanitized result for an asynchronous run; returns `None` until ready or after it was consumed. |
| `resume(session_id, prompt, ...)` | Runs `codex exec resume`; requires `confirm_inherited_permissions=True` because stored session policy is retained. It is not app-server `thread/resume`. |
| `fork(session_id, prompt, ...)` | Runs `codex exec fork`; result `session_id` is parsed from JSONL when Codex emits `thread.started`. |
| `review(cwd, uncommitted/base/commit, ...)` | Runs installed `codex exec review` for exactly one supported target. Arbitrary file lists are not supported. |
| `get_effective_config(cwd, ...)` | Diagnostic `config/read` query with a secret-filtered whitelist and layer/source metadata. |
| `list_configured_mcps(cwd, ...)` | Diagnostic app-server inventory. Advertised tool names are not proof that tool invocation is callable. |
| `list_effective_skills(cwd, ...)` | Diagnostic cwd-scoped `skills/list`; does not prove that a separate exec run used a skill. |
| `get_effective_capabilities(...)` | Combines local capability checks and explicit child/run unknown states. |

`resume()` and `fork()` require a specific stored session id and `confirm_inherited_permissions=True`: local CLI help exposes no replacement sandbox/approval flags for these commands, so stored session policy remains in force. The supplied `cwd` is validated and used as the subprocess launch cwd, but local help has no `-C` switch for resume/fork; it does not prove the stored session working root changed.

### App-server turns and events (Phase 3)

```python
from p4_codex_bridge import (
    ApprovalPolicy, CodexBridge, CodexPermissions, SandboxMode,
)

bridge = CodexBridge(allowed_roots=[r"F:\\safe\\workspace"])
turn = bridge.start_turn(
    "Reply exactly: OK",
    cwd=r"F:\\safe\\workspace",
    permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
)
try:
    for event in turn.events(timeout=120):
        print(event.type, event.data)
    print(turn.final_text)
finally:
    turn.close()
```

`start_turn()` returns a live ephemeral thread/turn handle. `turn.events()` is a bounded synchronous iterator. `CodexBridge.stream_events(prompt, ...)` closes its handle on normal terminal completion; if its consumer abandons the stream, the bridge retains the turn, detaches the old queue and allows recovery with `get_turn_handle(turn_id)`. `await bridge.astream_events(...)` provides the async iterator over that same implementation. `turn.subscribe(thread_id=..., turn_id=...)` creates an additional filtered in-process subscriber. `turn.partial_text`, `turn.final_text`, `turn.status`, `turn.pending_approval`, and `turn.interrupt()` expose the current turn state.

`stream_all_events(thread_id=..., turn_id=..., timeout=...)` multiplexes live handles already owned by this `CodexBridge` process; `astream_all_events(...)` is its async facade. It returns when the observed turns finish, or raises on timeout. It does not attach across processes or include turns created after the observed set has finished.

Lifecycle status is also available as `bridge.status(turn_id)`. `bridge.list_managed()` combines registered `exec` jobs and app-server turn status. `get_events(thread_id=..., turn_id=..., after_sequence=...)` replays only persisted lifecycle events. `get_event_metrics()` reports active streams, pending approvals, events received/dropped, and turns waiting for approval.

When `ApprovalPolicy.ON_REQUEST` is selected, approval handling is manual by default. On `ApprovalRequested`, call `bridge.approve(approval_id)` or `bridge.reject(approval_id)`; the equivalent CLI writes a decision to the local SQLite registry. The configured `approval_timeout_seconds` rejects a request when it expires. `ApprovalHandlingPolicy.AUTO_REJECT` and `NEVER_EXPECT_APPROVAL` are explicit rejection policies. There is no auto-approve-safe mode. Full-access sandbox requires explicit `ON_REQUEST`.

Use the default bounded queue (256) unless the consumer has a measured need to change it. Noncritical overflow is counted/dropped; critical events block the protocol reader. Read lifecycle replay after disconnect; message deltas are transient and are not replayed.

Not yet exposed: persistent app-server `thread/resume`, `thread/fork`, `send`/`steer`, session lookup, a shared resident manager, tool `requestUserInput`, MCP elicitation handling, and full replay of deltas. Exec resume/fork/review are separate subprocess operations and do not create app-server session handles.

## Typed controls

- `SandboxMode`: `READ_ONLY`, `WORKSPACE_WRITE`, `FULL_ACCESS`, mapped to the exact installed exec sandbox flags.
- `ApprovalPolicy`: `NEVER`, `ON_REQUEST` for exec; `AppServerApprovalPolicy` additionally models app-server `UNTRUSTED`.
- `ConfigPolicy`: `ISOLATED`, `PROJECT`, `EXPLICIT`; user-only is intentionally unsupported.
- `ReasoningSummary`: `AUTO`, `CONCISE`, `DETAILED`, `NONE`; `ModelVerbosity`: `LOW`, `MEDIUM`, `HIGH`.
- `ApprovalHandlingPolicy`: `MANUAL`, `AUTO_REJECT`, `NEVER_EXPECT_APPROVAL`. `AUTO_APPROVE_SAFE_ONLY` is planned and intentionally unavailable.
- `CodexPermissions`: sandbox, approval policy, writable roots and optional workspace-write network setting. Roots are absolute, existing directories and must stay within configured bridge allowed roots (or cwd when no roots are configured). Network is an OS sandbox/config control, not an MCP network filter.
- `RunStatus`: STARTING, RUNNING, WAITING_APPROVAL, COMPLETED, FAILED, INTERRUPTED, STOPPED, TIMED_OUT, ORPHANED. `WAITING_APPROVAL` is used for live turn status; it is not a `codex exec` state.
- `BridgeRun`: run id, Codex PID, worker PID, backend, cwd, model, profile, start time, status, exit code and last error.
- `RunResult`: success flag, bridge id, process exit code, `content`/`text_output`, sanitized stderr, `structured_output`, optional `raw_output`, parsed Codex `session_id`, normalized error and duration.

`allowed_roots` is an optional bridge-side cwd allowlist. It does not change Codex sandbox policy. `reasoning_effort` is passed to Codex configuration; use the selected model's `supportedReasoningEfforts` from `list_models()` rather than assuming every value is available.

## Model and structured output

`list_models()` returns dictionaries from the installed app-server model catalog, including each advertised reasoning-effort list. It may return models the current account cannot infer with. The catalog is dynamic, not hardcoded.

Pass a JSON Schema object with `output_schema`. The worker writes it to a temporary file, uses the installed `--output-schema` option, deletes the schema file, and parses the final agent message into `structured_output`. Invalid JSON makes the result fail with `STRUCTURED_OUTPUT_INVALID`; the bridge does not silently repair JSON or independently validate full schema conformance. `capture_last_message=True` encapsulates the CLI's `--output-last-message` file and uses that file as the authoritative final text, including when it is empty.

Typed tuning is `model`, `reasoning_effort`, `reasoning_summary` (`auto`, `concise`, `detailed`, `none`) and `verbosity` (`low`, `medium`, `high`). Reasoning effort is a non-empty string advertised per model, not a hardcoded enum; inspect `list_models()` for that model's supported values. These options do not guarantee model entitlement.

## Configuration policies

- `isolated`: adds `--ignore-user-config`; auth remains in the official Codex login system. Do not infer that local project config, AGENTS, skills, or MCPs are suppressed.
- `project`: normal Codex layered settings for the requested cwd (including user config where Codex loads it).
- `explicit`: normal layered settings plus simple scalar/list TOML-compatible values passed with `-c`.
- `user`: rejected because installed Codex does not separately select user-only configuration.

`get_effective_config()` uses app-server `config/read`, not the same child process as `exec`; it returns only selected non-secret primitive fields and layer source types. Its result is diagnostic and must not be reported as an exact effective config for another run. For MCPs, `list_configured_mcps()` reports configured/enabled/advertised-tool state separately from callability, child visibility and per-run effectiveness. `list_effective_skills()` has the same diagnostic-child boundary. AGENTS loading is not currently acknowledged by `codex exec`; use the manual marker smoke to confirm a specific cwd/policy combination.

## App-server transport

The official Python package `openai-codex` is available but is not installed as a dependency here. Phase 3 implements the narrow streaming/approval surface over the installed stdio JSON-RPC protocol; the reader is centralized per live turn and is not a resident multi-thread manager. See [events](EVENTS.md), [approvals](APPROVALS.md), [capability matrix](CAPABILITY_MATRIX.md), [architecture](ARCHITECTURE.md), and [lifecycle](LIFECYCLE.md).
