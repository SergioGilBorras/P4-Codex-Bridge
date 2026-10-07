# Architecture

## Current implementation

```text
P4 caller -> CodexBridge
                +-> codex exec -> managed worker -> SQLite runs
                +-> app-server model/list -> dynamic model catalog
                +-> app-server thread/start + turn/start
                      -> one JSON-RPC reader -> normalized event fanout
                      -> approval requests -> explicit response through owning connection
```

- `client.py` is the public facade, cwd/parameter validation, exec lifecycle and local registry access.
- `runtime_manager.py` owns the resident app-server process, central JSON-RPC reader, threads/turns, approvals and app-server resource scheduling. The lower-level `app_server.py` transport is also used by short-lived operations.
- `events.py` defines normalized event/approval models, JSON decoding, message assembly, safe serialization and bounded event subscriptions.
- `registry.py` migrates the SQLite database in place. It stores exec process metadata, sanitized lifecycle event replay and approval decisions. It never stores prompts, login credentials or environment values. Message deltas/tool outputs are not persisted.
- `_worker.py` remains the detached Phase 1 supervisor for `codex exec`.
- `runtime.py` holds shell-free process resolution, allowlisted environment, output parsing and redaction.
- `cli.py` exposes operator commands for both exec jobs and app-server turn state.
- Python is the sole implementation. The independent JavaScript runtime, duplicate process/security logic, npm metadata and JS tests were removed before API freeze because no bridge consumer requires that runtime. This does not remove or modify Planning-Agent source files.

The recorded reference snapshot is Codex CLI `0.160.1`, resolved from the
installed npm package `@openai/codex` (package root discovered through the
`codex` PATH shim; package entry point `bin/codex.js`). This installation does
not ship a standalone schema artifact in the package file list; the supported
mechanism used by preflight is the generated local schema command
`app-server generate-json-schema --out <temporary-directory> --experimental`.
The bridge parses the generated JSON, computes a SHA-256 identity, and retains
only a compact method snapshot. The bridge parsed the installed schema on
2026-10-07, recording version `codex-cli 0.160.1`, source
`GENERATED_LOCAL_SCHEMA`, SHA-256
`4a02439823bc98fbbca86d9f934d5a90a638b41ec16c635c8c4448b2b9e14867`, and
262 literal protocol method names. The normal sandbox invocation previously failed with
`EPERM` while resolving the user profile; schema generation succeeded with the
required local filesystem access. No methods are inferred from version or docs.
A schema match is only
`SUPPORTED_WITH_LIMITATIONS`; a successful runtime RPC confirms its method;
method-not-found is explicit negative evidence. See the current closeout table
in [capability matrix](CAPABILITY_MATRIX.md). The app-server remains
experimental.

`codex exec` backs direct one-shot `run()`, queued managed `start()`, and
separate `resume()`, `fork()` and `review()` operations. App-server thread and
turn lifecycle is managed separately by the resident runtime; thread resume,
fork and steer are distinct operations, and an app-server restart does not
adopt active turns. See the release snapshot for capability preflight limits.

The protocol reader is centralized per app-server connection and distributes events to bounded in-process subscriber queues. Critical lifecycle and approval events apply backpressure; noncritical queue overflow is counted and dropped. Lifecycle replay is local SQLite persistence, not upstream replay. Events and approvals are sanitized before persistence; message deltas remain transient.

## Capability classification

| Surface | Verified capability | Bridge state |
|---|---|---|
| A. `codex exec` | One-shot stdin/JSONL, model/cwd/sandbox/approval flags, JSON schema/final-message file; CLI also has `resume`, `fork`, `review`. | Run, resume, fork, supported review targets, structured output and last-message capture implemented; real smoke for these Phase 4 operations remains unrun. |
| B. `codex app-server` | Experimental local JSON-RPC surface; installed generated-schema command plus runtime initialize handshake. | Resident manager, threads/turns, streaming, manual approvals, recovery metadata and shared scheduling are implemented. Feature methods are mapped explicitly and runtime-gated; local schema generation is NOT_CONFIRMED in this restricted session. |
| C. Official Python SDK | `openai-codex` documented; not installed as a runtime dependency. | Not used at runtime. The bridge keeps a narrow CLI/app-server boundary; SDK adoption is a future compatibility decision. |
| D. CLI/config | Native Codex config, profiles, sandbox and approval flags, `-c`, `--ignore-user-config`, login, MCP and feature commands. | Exec maps verified settings; diagnostic app-server APIs expose whitelisted config, MCP and skills metadata. Project/AGENTS/MCP child behavior remains unconfirmed for exec. |
| E. Not confirmed/available to this child process | IDE Codex tools/MCP and Codex Apps handles are not forwarded by this bridge. Skills/AGENTS/MCP loading behavior remains config/cwd-dependent and has not been confirmed for an exec run. | Session visibility, config, enabled/callable, child-visible and effective-for-run remain distinct statuses. |

The official [SDK README](https://github.com/openai/codex/blob/main/sdk/python/README.md), [API reference](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md), [app-server overview](https://developers.openai.com/blog/codex-as-a-platform), [protocol schema](https://github.com/openai/codex/tree/main/codex-rs/app-server-protocol) and [CLI docs](https://developers.openai.com/codex/cli/) are the documentation references. The separate [manual OAuth token sharing guide](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) is not used by the Bridge.

## Permissions and approval safety

- `codex exec` uses verified CLI enums: `read-only`, `workspace-write`, `danger-full-access`; approval policies `never` and `on-request`.
- App-server `thread/start` accepts those exact sandbox and approval enum values. `turn/start.sandboxPolicy` exposes `readOnly`, `workspaceWrite` (with `writableRoots` and `networkAccess`), and `dangerFullAccess`.
- Bridge workspace-write maps writable roots to the validated cwd and network access false. This does not claim to override every other native config/sandbox policy.
- Full access requires an explicit approval policy. No profile auto-approves. `AUTO_APPROVE_SAFE_ONLY` remains planned because there is no deterministic action classifier.
- Approval commands/file/permissions use distinct response shapes. Unknown server requests are answered with method-not-handled and surfaced as `ServerError` rather than implicitly accepted.

## Later phases

Phase 5 adds the initial resident stdio manager, shared thread lifecycle, a SQLite registry, local lock, health and recovery reports. Thread resume/reconnection, durable queued submissions, manager-level approvals, cross-process service mode and exec worker adoption remain incomplete. Exec resume/fork/review and structured-output/config discovery remain separate APIs. Keep Orchestrator task state separate from bridge-owned Codex process/thread state. See [lifecycle](LIFECYCLE.md) and [recovery](RECOVERY.md).
# Resource scheduling

`CodexRuntimeManager` uses the persistent `ResourceScheduler` before starting app-server turns. SQLite atomically claims a queue row and its workspace lock; terminal outcomes release the lock and make the next eligible work dispatchable. The scheduler owns resource availability only. It does not select P4 tasks or implement business priority.
# Same-machine daemon command path

External Python/CLI clients write a validated request into
`bridge_runtime_commands`. The resident service atomically claims one command,
validates it again, then calls the existing public exec or app-server API. Those
APIs retain the common resource scheduler, limits, workspace locks and
observability. The command table is a request/ack transport, not a second job
scheduler. A crash after claim yields an unknown command outcome and is not
replayed, preventing silent duplicate work.
