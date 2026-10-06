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
- `app_server.py` owns one app-server process per live turn, demultiplexes JSON-RPC responses, notifications and server requests, and closes only its own process.
- `events.py` defines normalized event/approval models, JSON decoding, message assembly, safe serialization and bounded event subscriptions.
- `registry.py` migrates the SQLite database in place. It stores exec process metadata, sanitized lifecycle event replay and approval decisions. It never stores prompts, login credentials or environment values. Message deltas/tool outputs are not persisted.
- `_worker.py` remains the detached Phase 1 supervisor for `codex exec`.
- `runtime.py` holds shell-free process resolution, allowlisted environment, output parsing and redaction.
- `cli.py` exposes operator commands for both exec jobs and app-server turn state.
- `src/`, `bin/` and `tests/` retain the existing Node compatibility path.

The installed reference is Codex CLI `0.160.1`, Node `v22.15.0`. The local v2 app-server schema was generated with `codex app-server generate-json-schema --experimental`. The app-server reports itself as experimental. See [capability matrix](CAPABILITY_MATRIX.md) for the exact notifications, request methods and verified fields.

`codex exec` backs one-shot `run()`/`start()` and the separate CLI operations `resume()`, `fork()` and `review()`. These operations each use one managed subprocess; resume/fork retain stored session settings and do not become persistent app-server handles. `start_turn()` creates an ephemeral app-server thread and one turn. A live `CodexTurn` owns that server process; `close()` terminates only that bridge-managed process. `interrupt()` uses the installed JSON-RPC `turn/interrupt` method. The Bridge does not yet resume an app-server thread or multiplex multiple turns over a resident server.

The protocol reader is centralized per app-server connection and distributes events to bounded in-process subscriber queues. Critical lifecycle and approval events apply backpressure; noncritical queue overflow is counted and dropped. Lifecycle replay is local SQLite persistence, not upstream replay. Events and approvals are sanitized before persistence; message deltas remain transient.

## Capability classification

| Surface | Verified capability | Bridge state |
|---|---|---|
| A. `codex exec` | One-shot stdin/JSONL, model/cwd/sandbox/approval flags, JSON schema/final-message file; CLI also has `resume`, `fork`, `review`. | Run, resume, fork, supported review targets, structured output and last-message capture implemented; real smoke for these Phase 4 operations remains unrun. |
| B. `codex app-server` | Experimental stdio/unix/websocket/off JSON-RPC; model discovery; thread/turn methods; lifecycle, delta, tool, error, approval notifications/requests; config, MCP, skills, filesystem and command methods. | Model discovery plus ephemeral one-turn streaming, interruption, manual approvals and partial lifecycle persistence implemented. Many protocol methods remain unexposed. |
| C. Official Python SDK | `openai-codex` documented for threads, turns, events, approvals and existing Codex authentication; package not installed in this environment. | Not a runtime dependency. Current API uses installed CLI and narrow local app-server protocol; re-evaluate SDK adoption in Phase 5 against lifecycle/recovery needs. |
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
