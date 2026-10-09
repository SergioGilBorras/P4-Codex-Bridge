# Python API

## Public surface and stability

Consumers should import contracts only from `p4_codex_bridge`. Its explicit
package-root allowlist remains the stable public boundary in 1.1. `CodexBridge` is the
in-process facade; `CodexServiceClient` is the stable boundary for a separate
process submitting work to the resident service. Protocol-specific lifecycle
operations remain experimental where they depend on evolving app-server RPCs.

| Component | Classification | Consumer guidance |
|---|---|---|
| `CodexBridge` | STABLE for typed exec operations, managed scheduled `start`, discovery, inspection and cancellation; app-server-specific methods remain experimental | Preferred in-process facade. |
| `CodexServiceClient` | STABLE for availability check, typed submit/create/start, command wait, inspect/watch and cancel | Preferred cross-process submission and run-observation boundary. Service health/status and approval resolution are CLI operations in 1.1. |
| `CodexRuntimeManager` | INTERNAL | Runtime implementation; not a consumer import path. |
| Runtime limits | EXPERIMENTAL service TOML configuration | SQLite scheduler types are internal and not exported at package root. |
| scheduler / `ResourceScheduler` | INTERNAL | SQLite queue implementation; do not import it from consumers. |
| registry / SQLite schema | INTERNAL | Persistence implementation can migrate without consumer changes. |
| app-server transport and process helpers | INTERNAL | Protocol and OS process details are not public contracts. |

The package root has an explicit export allowlist. Runtime manager, service
implementation, scheduler, registry, SQLite, transport, canonicalization and
process helpers are not package-root exports. `tests_py/test_public_api.py`
locks this boundary. Some exported value types and methods remain experimental;
being importable does not make them stable.

`CapabilityStatus` is the generic compatibility enum. App-server protocol state
uses the explicitly named experimental `AppServerCapabilityStatus`; the two
are separate types. `AppServerCapabilitySet`, `ApprovalRequest`, event models,
`CodexTurn`, and `AppServerApprovalPolicy` are exported for advanced protocol
users but remain EXPERIMENTAL. The current public call contract is summarized in [execution contract](CONTRACT.md) and
covered by `tests_py/test_public_api.py`.

`CodexVersionInfo`, `CapabilitySet`, `CompatibilityResult`,
`CompatibilityStatus`, and `assess_compatibility` are stable diagnostic value
contracts. `ForegroundService`, `ServiceConfig`, `maintenance_report` and
`database_health` are implementation details in `service.py`, not package-root
exports. Operate the resident process through the CLI and submit work through
`CodexServiceClient`.

### Method-level status

For `CodexBridge`, the intended STABLE methods are `get_version`,
`get_capabilities`, `start`, `run`, `get_run`, `status`, `list_runs`,
`resolve_run_reference`, `inspect`, `watch`, `stop`, `kill`, `cancel`, and
`read_result`.

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
`run(prompt, *, cwd, profile, model, timeout_seconds, permissions,
reasoning_effort, reasoning_summary, verbosity, output_schema,
skip_git_repo_check=False, capture_last_message, include_raw_output,
config_policy, config_overrides, metadata, announce_run, security_policy)` is
closed and rejects unknown keywords. `start()` accepts the same
`skip_git_repo_check=False` option for managed/scheduled exec. Stable APIs are
synchronous; `watch` is a synchronous iterator.
Async `awatch`/event streaming and app-server lifecycle APIs are experimental.
`CodexBridge.recover_exec_runs()` reconciles owned worker identities and accepts
only a structurally valid result file matching the bridge run ID. It marks
unverifiable claimed work `LOST`; it never restarts a Codex turn.

All `CodexRuntimeManager` lifecycle, scheduling, metrics, health, recovery,
thread, turn and cancel methods are EXPERIMENTAL. `CodexTurn` is an EXPERIMENTAL
returned handle. `ResourceScheduler`, `RunRegistry`, `AppServerConnection`,
SQLite schema helpers and `_worker` process functions are INTERNAL. Consumers
should not use them as a substitute for a missing facade operation.

### `CodexBridge` methods

The intended stable `CodexBridge` contract is `get_version`,
`get_capabilities`, `run`, `start`, `get_run`, `status`, `list_runs`,
`resolve_run_reference`, `inspect`, `watch`, `stop`, `kill`, `cancel`, and
`read_result`. Model/config, MCP and skill diagnostics are best-effort
observations, not a guarantee of child effectiveness. `resume`, `fork`, and
`review` are separately gated exec operations and remain
EXPERIMENTAL until verified against the supported CLI range. Model/config,
MCP, skill and capability diagnostics; `format_run_announcement`; `awatch`;
and app-server stream/approval methods are EXPERIMENTAL.

`start()` is the managed/scheduled `exec` path; `run()` deliberately retains
the direct one-shot path. App-server turns and scheduled exec runs share the
same global/backend/profile limits and workspace locks. `cancel()` cancels
queued jobs before launch, signals managed exec workers with an identity-checked
termination fallback, and routes app-server interruption to its owner. The
backends keep their native lifecycle semantics and are not interchangeable.

### Lifecycle verbs

`cancel` withdraws queued work and requests the owning backend's controlled
termination for active work. `interrupt` asks an active app-server turn to stop
while retaining its thread when supported. `stop` requests cooperative
termination of a managed exec run. `kill` is the identity-checked OS
process-tree fallback. These operations are not aliases.

### Skip the Git repository check

`CodexBridge.run()` and `CodexBridge.start()` accept the strictly typed
`skip_git_repo_check: bool = False` parameter. The default leaves the Codex
command unchanged. When true, the bridge checks the installed
`codex exec --help` output and adds `--skip-git-repo-check` exactly once to the
`codex exec` argument vector. If the installed CLI does not advertise the flag,
the call raises `CapabilityUnavailableError` before launching or queueing work.

```python
from pathlib import Path
from p4_codex_bridge import CodexBridge

bridge = CodexBridge(allowed_roots=[r"C:\P4"])
workspace = Path(r"C:\P4\existing-scratch-directory")  # must already exist
allowed_root = Path(r"C:\P4")

# Existing Git repository: the default check remains enabled.
result = bridge.run("Inspect the project", cwd=r"C:\P4\project")

# Existing directory without .git, including an empty temporary directory.
result = bridge.run(
    "List the available files",
    cwd=workspace,
    skip_git_repo_check=True,
)

# Empty temporary directory: place it inside an allowed root; TemporaryDirectory
# creates the existing cwd for the duration of the call.
from tempfile import TemporaryDirectory
with TemporaryDirectory(prefix="codex-work-", dir=allowed_root) as temporary_cwd:
    result = bridge.run(
        "Inspect the empty workspace",
        cwd=temporary_cwd,
        skip_git_repo_check=True,
    )
```

No new directory or artificial Git repository is required. The bridge still
requires an existing `cwd` permitted by `allowed_roots`. The option only skips
Codex's Git-context check; it does not change `RunSecurityPolicy`, sandbox,
approval policy, MCP policy, authentication, or path validation. The caller must
choose it explicitly because Codex receives less repository context.

Check availability without starting an inference:

```python
if not bridge.get_capabilities()["exec"]["skip_git_repo_check"]:
    raise RuntimeError("Installed Codex CLI does not support this option")
```

If the option is unavailable, `run()` and `start()` raise
`CapabilityUnavailableError`; they do not retry without the flag. Catch that
error or check the capability field above before submitting. A pre-existing
directory outside Git works the same way as the temporary example; it still
must exist and be allowed by bridge path policy.

The option is intentionally limited to `run()` and managed `start()`. It is not
forwarded through `resume()`, `fork()`, `review()`, `CodexServiceClient`, or the
CLI/service submit payloads in the current implementation. See the [current execution contract](CONTRACT.md) for supported signatures.

### Errors and resource scheduling boundary

The package defines `BridgeError`, `ConfigurationError`,
`CapabilityUnavailableError`, `ServiceUnavailableError`, `ConflictError`,
`QueueFullError`, `ResourceUnavailableError`,
`RunNotFoundError`, `RunStateError`, `BackendError`, `AuthenticationError`,
`ProtocolError`, and `BridgeTimeoutError`. `QueueFullError` is raised by the
internal persistent scheduler. Error normalization across all facade
methods is still PARTIAL; some methods preserve `ValueError`, `KeyError`, or
backend-specific failures for compatibility.

## Resident runtime (experimental)

`CodexRuntimeManager(cwd=..., database_path=...)` owns one app-server child.
Call `start()`, `health()`, `create_thread(...)`, `start_turn(thread_id,
prompt)`, `list_threads()`, `list_turns()`, `get_metrics()`, `recover()` and
`stop(mode="WAIT" | "INTERRUPT" | "FORCE")`. It supports context-manager use.
Turn submissions pass through the persistent app-server resource queue and
return a handle while queued. The default active-turn limit is conservative.
The manager is experimental; `CodexBridge.start_turn()` remains an ephemeral
connection path; managed `CodexBridge.start()` exec workers use the shared queue.
Persistent thread operations are `resume_thread(thread_id, model=None)`,
`fork_thread(thread_id, last_turn_id=None, before_turn_id=None, ephemeral=False,
model=None)`, and `steer_turn(thread_id, turn_id, text)`. Resume reopens the
thread and starts no turn; `start_turn` on that thread creates a new turn.
Steer appends input to the specific active turn using the protocol's expected
turn ID. Fork is a server-side operation, not a local copy.

Manager approvals use `list_pending_approvals()`, `get_approval(id)`,
`approve(id)`, and `reject(id)`. CLI `approvals`, `approve`, and `reject` use
the shared registry. A decision is accepted only while the owning server
instance and original JSON-RPC request are live. Restart makes pending requests
stale; timeout rejects. `thread/turns/list` reconciliation is bounded to one
100-turn page and matching terminal IDs; active turns are not adopted. Local
lifecycle replay is partial and remote delta replay is unavailable.

## Discovery and watch

`CodexBridge.start/run(..., metadata={...})` and `start_turn(..., metadata=...)`
accept bounded, redacted operational metadata. `announce_run=True` writes only
sanitized announcements to the configured logger. Use `list_runs(active=...,
task=..., agent=..., backend=..., status=...)`, `resolve_run_reference(id)`,
`inspect(id)`, `watch(id, follow=...)` or `awatch(...)`. `watch` is read-only and
independently polls persisted events. See [live observability](LIVE_OBSERVABILITY.md).

## Install / import

The package has no third-party runtime dependency beyond the Python 3.10 TOML compatibility dependency. Current source version `1.1.0` is defined once in `p4_codex_bridge.__version__` and read dynamically by setuptools and `p4-codex --version`. Install this repository into the caller's Python environment with `pip install -e .`, or install a built wheel. Codex CLI remains an external installed prerequisite. Python >=3.10 is declared.

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
| `get_effective_capabilities(..., include_diagnostics=False)` | Returns machine-readable local capability state. With `include_diagnostics=True` and a cwd, adds config/MCP/skills results from a short-lived app-server child. It deliberately leaves host-session visibility and effective state for a separate `exec` run unknown. |

`resume()` and `fork()` require a specific stored session id and `confirm_inherited_permissions=True`: local CLI help exposes no replacement sandbox/approval flags for these commands, so stored session policy remains in force. The supplied `cwd` is validated and used as the subprocess launch cwd, but local help has no `-C` switch for resume/fork; it does not prove the stored session working root changed.

### App-server turns and events

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

Still not exposed: tool `requestUserInput`, MCP elicitation handling, automatic reconnect, active-turn adoption, and full remote delta replay. Persistent manager `resume_thread`, `fork_thread`, and `steer_turn` are experimental app-server APIs. Exec resume/fork/review are separate subprocess operations and do not create app-server session handles.

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

`get_effective_config()` uses app-server `config/read`, not the same child process as `exec`; it returns only selected non-secret primitive fields and layer source types. Its result is diagnostic and must not be reported as an exact effective config for another run. For MCPs, `list_configured_mcps()` reports configured/enabled/advertised-tool state separately from callability, child visibility and per-run effectiveness. `list_effective_skills()` has the same diagnostic-child boundary. `get_effective_capabilities(include_diagnostics=True)` groups those three diagnostic responses, but never upgrades them to `EFFECTIVE_FOR_RUN`. `config_policy="isolated"` is not supported by the diagnostic app-server because it has no equivalent to exec's `--ignore-user-config`; the API returns `NOT_SUPPORTED` for those diagnostic fields instead of guessing. AGENTS loading is not acknowledged by `codex exec`; the marker script requires an explicit `--allow-unfiltered-mcps` acknowledgement before it can start a model run.

## Foreground service

`CodexServiceClient` is the intended public boundary for a running daemon. It
provides typed `submit_exec_run`, `create_thread`, `start_turn`,
`wait_command`, `inspect`, `watch`/`awatch`, and `cancel`; it does not expose
SQLite. The current client does not provide health/status, approval resolution,
or thread/turn wait convenience methods; use CLI for those operations. Service
manager, config loader and database functions remain internal.

## App-server transport

The official Python package `openai-codex` is not a runtime dependency here.
App-server protocol handling remains experimental and is gated by discovered
installed-schema capabilities. See [events](EVENTS.md), [approvals](APPROVALS.md),
[capability matrix](CAPABILITY_MATRIX.md), [architecture](ARCHITECTURE.md), and
[lifecycle](LIFECYCLE.md).
# Cross-process service client

Use `CodexServiceClient` when the resident service owns scheduling and app-server
lifecycle. Its typed public request models are `ExecRunSubmission`,
`CreateThreadRequest`, and `StartTurnRequest`; `CommandResult` reports command
status/result/error. Methods are `submit_exec_run`, `create_thread`,
`start_turn`, and `wait_command`. Requests require the service to be active and
do not spawn it. Optional idempotency keys prevent duplicate command rows.

The client also exposes `inspect(run_id)`, `cancel(run_id)`, and read-only
`watch(run_id)`/`awatch(run_id)` helpers over the shared journal. These typed
request/result classes are part of the current public consumer interface. Do not import
service database/scheduler internals from consumers.
