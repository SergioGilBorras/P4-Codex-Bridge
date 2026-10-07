# P4-Codex-Bridge 1.0 contract

This records the frozen public surface for the 1.0.0 release. The package
version is defined by `p4_codex_bridge.__version__`.

## Freeze status

| Contract | Status | Boundary |
|---|---|---|
| Python package-root exports | FROZEN | Exact `p4_codex_bridge.__all__`; implementation helpers are not exported. |
| `CodexBridge.run` signature | FROZEN | Explicit typed keyword surface; no arbitrary keyword forwarding. |
| `CodexServiceClient` typed requests | FROZEN | Cross-process submit/create/start uses typed requests and repeats daemon validation. |
| `CodexRuntimeManager` | FROZEN as INTERNAL | Not a package-root export or supported consumer entry point. |
| CLI command tree | FROZEN | Tree below; unlisted commands are not part of this candidate contract. |
| CLI output | FROZEN | Success stdout is JSON, except documented JSONL streams and foreground service logs to stderr. |
| CLI exit codes | FROZEN | Table below. |
| TOML names and environment variables | FROZEN | Strict sections/keys; unknown keys fail. No `config_version` field. |
| Per-run MCP filtering | NOT_SUPPORTED | The bridge rejects required isolation and unknown effective MCP state by default. |
| App-server RPC surface | EXPERIMENTAL | Local generated schema and observed runtime RPCs are capability-gated; not a stable Codex protocol promise. |

## Python API

Stable exports are `CodexBridge`, `CodexServiceClient`, `ExecRunSubmission`,
`CreateThreadRequest`, `StartTurnRequest`, `CommandResult`, `CodexPermissions`,
`RunSecurityPolicy`, `ProjectTrust`, `SecurityDecision`,
`SecurityDecisionResult`, `validate_run_security`, `CodexVersionInfo`,
`CapabilitySet`, `CompatibilityResult`, `CompatibilityStatus`,
`assess_compatibility`, `CapabilityStatus`, `RunResult`, `BridgeRun`, `RunStatus`, `ConfigPolicy`,
`SandboxMode`, `ApprovalPolicy`, `ApprovalHandlingPolicy`,
`BridgeError`, `ConfigurationError`,
`CapabilityUnavailableError`, `ServiceUnavailableError`, `ConflictError`,
`RunSecurityRejectedError`, `CapabilityIsolationUnavailableError`,
`QueueFullError`, `ResourceUnavailableError`, `RunNotFoundError`,
`RunStateError`, `BackendError`, `AuthenticationError`, `ProtocolError`,
`BridgeTimeoutError`, and `__version__`.

Exported but EXPERIMENTAL protocol contracts are `AppServerCapabilityStatus`,
`AppServerCapabilitySet`, `ApprovalRequest`, `ApprovalError`,
`ApprovalTimeoutError`, `ApprovalRejectedError`, `CodexEvent`,
`EventStreamError`, `EventDecodeError`, `ToolEventError`,
`AppServerApprovalPolicy`, and `CodexTurn`. `CapabilityStatus` names the generic
compatibility state; `AppServerCapabilityStatus` explicitly names RPC/schema
evidence so the two enums cannot be confused by consumers.

`CodexBridge.run()` and `start()` are synchronous. `watch()` is a synchronous
iterator. `CodexServiceClient` methods are synchronous and bounded by their
timeout. Async `awatch` and app-server event streams, direct app-server lifecycle
types, and diagnostic discovery whose result depends on an experimental schema
remain experimental. `CodexRuntimeManager`, scheduler, registry, transport,
SQLite, worker and migration helpers are internal.

## CLI tree

```text
p4-codex
├── run
├── start
├── ps
├── inspect
├── watch
├── status / result / stop / kill
├── models
├── events
├── approvals / approve / reject
├── capabilities / version / resources / limits / cancel
├── service run / status / stop / restart / recover / demo
├── health / metrics
├── config show / validate
├── doctor
├── maintenance status / clean
├── submit exec
├── thread create
└── turn start
```

Each leaf accepts `--json`. It is also the default output mode. Ordinary
successes are one JSON document; `watch` and `events` emit JSONL. Argument
errors emit a single sanitized JSON usage error and exit 2. The informational
root flags `--help` and `--version` use ordinary text output. Errors emit a
single sanitized `{"ok":false,"error":{"code":...,"message":...}}` JSON
record to stdout and a sanitized diagnostic to stderr. `service run` is
foreground mode: logs go to stderr and there is no single JSON stdout document.

| Exit | Meaning |
|---:|---|
| 0 | Operation succeeded, including a healthy/known stopped service status. |
| 1 | Other bridge failure or unsuccessful one-shot result. |
| 2 | Usage or request/config validation failure. |
| 3 | Security policy rejection. |
| 4 | Required capability unavailable. |
| 5 | Resident service unavailable. |
| 6 | Request/operation timeout. |
| 7 | Backend failure. |
| 8 | Queue/resource/run-state conflict or uncertain recovery state. |

## Configuration

Precedence for service configuration: explicit CLI option, supported bridge
environment variable, TOML value, default. Exact env variables:

* `P4_CODEX_BRIDGE_CONFIG`
* `P4_CODEX_BRIDGE_STATE_DIR`
* `P4_CODEX_BRIDGE_CODEX_EXECUTABLE`

TOML accepts only `[service]`, `[runtime]`, `[logging]`, `[codex]`, and
`[retention]` with keys from `p4-codex.example.toml` and `docs/CONFIGURATION.md`.
Unknown sections/keys and unsupported values fail fast. There is no
`config_version`; future incompatible changes require explicit migration or a
new format. Config never stores authentication secrets.

The supported package artifacts are wheel and sdist. On Windows the supported
entry points are `python -m p4_codex_bridge` and the packaged `p4-codex.cmd`;
the generated console-script `.exe` remains optional/environment-dependent.

## Security boundary and known limits

No per-run MCP allow/deny filter or reliable empty-MCP receipt is available.
`require_mcp_isolation=True` is rejected. Default `UNKNOWN` project/MCP state
does not mean no MCPs: execution is rejected. Trusted project context and
external MCP side effects require explicit opt-in/acknowledgement and produce a
warning. This is an unfiltered-risk acknowledgement, not isolation. Project
config, AGENTS and skills effectiveness remain NOT_CONFIRMED unless a run-level
receipt exists. `danger-full-access` and automatic approvals are never defaults.

## Capability evidence

Schema presence means `SUPPORTED_WITH_LIMITATIONS` until a successful runtime
RPC confirms the concrete method. Missing schema is `UNKNOWN`; it is not
`UNSUPPORTED`. A runtime method-not-found response is explicit negative
evidence. Newer Codex versions are not rejected by version number alone.

The local installed Codex package identified in the 2026-10-07 audit was
`@openai/codex` 0.160.1, with `bin/codex.js` as package entry point. The
installed `app-server generate-json-schema` command completed locally and
produced source `GENERATED_LOCAL_SCHEMA`, SHA-256
`4a02439823bc98fbbca86d9f934d5a90a638b41ec16c635c8c4448b2b9e14867`, and
262 protocol method names. This is schema evidence only; required app-server methods remain
`SUPPORTED_WITH_LIMITATIONS` until startup handshake/runtime confirms them. The
normal sandbox invocation had failed with `EPERM` before CLI dispatch, but that
was an environment access restriction, not an absent schema. The app-server
protocol remains experimental. `app_server.structured_output` is `UNKNOWN`
because `outputSchema` was not verified in the `turn/start` schema. Exec
capability remains independent.

## Final release-gate evidence (2026-10-07)

The clean wheel and sdist built and installed. From a fresh wheel venv, module
version/help, CMD launcher, config validation, service status and elevated
doctor passed. Doctor found Codex 0.160.1, ChatGPT login and app-server, with
the locally generated schema. Required app-server methods remain
`SUPPORTED_WITH_LIMITATIONS`.

The daemon smoke completed one cross-process turn with requested model
`gpt-6-luna` and exact output `OK`; read-only watch observed the run and the
service stopped with no active runs, queued work, workspace locks, approvals or
pending payloads. The API did not expose effective model identity or token
usage, so both remain `NOT_CONFIRMED`. The smoke explicitly acknowledged the
unfiltered configured MCP risk; it does not establish MCP isolation.
