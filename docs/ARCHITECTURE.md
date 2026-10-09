# Architecture

## Current components

    Python consumer / operator CLI
           |
           +--> CodexBridge facade (client.py)
           |     +--> direct run(): detached _worker.py --> codex exec
           |     +--> managed start(): SQLite queue --> _exec_dispatch.py --> _worker.py --> codex exec
           |     +--> runtime manager --> app-server thread/turn JSON-RPC
           |
           +--> local service / CodexServiceClient (typed requests)
                 +--> SQLite command transport --> resident service validation
                 +--> shared resource scheduler / runtime manager

- `client.py` exposes typed Python APIs, validates requests, scopes `cwd` using `allowed_roots`, and records result metadata.
- `runtime.py` resolves the Codex command, constructs argument arrays with `shell=False`, filters child environment variables, parses JSONL and redacts outputs.
- `_worker.py` supervises exec subprocesses, timeouts, stop requests, output size and temporary files.
- `_exec_dispatch.py` starts claimed managed exec jobs.
- `runtime_manager.py` owns the resident app-server connection and thread/turn lifecycle, including normalized events, approvals and resource dispatch. App-server methods are experimental.
- `scheduler.py` and `registry.py` manage local SQLite queue/locks, runs and sanitized lifecycle metadata.
- `service.py` and `service_client.py` expose local foreground operation and typed cross-process requests. The service revalidates requests.
- `cli.py` exposes operator commands.

## Execution models

| Path | What it does | Scheduling | Limit |
|---|---|---|---|
| `CodexBridge.run()` | Synchronous `codex exec`, returns `RunResult` | Not queued | One request/worker; explicit timeout |
| `CodexBridge.start()` | Managed `codex exec`, returns `BridgeRun` | Shared SQLite resource queue | Pending payload may be stored until dispatch |
| `CodexBridge.resume()/fork()/review()` | Separate `codex exec` operations | Their own typed contracts | Stored session policy or review-target constraints |
| App-server thread/turn APIs | Resident JSON-RPC lifecycle, events and approvals | Shared scheduler where applicable | Experimental method support |
| Service client/CLI | Typed cross-process commands | Revalidated by resident service | Same-user local state boundary |

The scheduler controls Codex resource availability, not the priority of business tasks in consumer applications. Direct `run()` is not an implicit managed job.

## Workspace, state and content

`cwd` must already exist and, if `allowed_roots` are specified, must fall within the permitted canonical paths. It need not be a Git repository for Python `run()` or `start()` **when** `skip_git_repo_check=True` and the installed CLI supports the flag. The default remains `False`.

Prompt text is sent through stdin, not command arguments. **Queued managed submissions can persist a bounded pending prompt payload in SQLite until claim/cancellation**; it is therefore inaccurate to describe all submission paths as never persisting prompts. Registry metadata and sanitized lifecycle events remain separate from the prompt. The bridge also maintains temporary result and optional schema/last-message files.

## Security and capability boundaries

Filesystem sandbox, allowed roots and approval policy are different controls. External MCP actions can act outside the filesystem sandbox; no supported per-run MCP allowlist is guaranteed. The bridge applies `RunSecurityPolicy` before relevant execution paths, with explicit trust/risk acknowledgement for unfiltered external tools.

Capability discovery from CLI help/generated schema does not prove account entitlement or effective capabilities of a later child run. A diagnostic app-server's MCP/skills inventory is not a receipt for `codex exec`. See [security](SECURITY.md), [capabilities](CAPABILITY_MATRIX.md), and [MCP](MCP.md).

## Recovery

The local scheduler and registry persist states and support conservative recovery. Unverifiable claimed work is not automatically replayed; active app-server turns are not blindly adopted after a restart. Message deltas are not available as durable replay. See [recovery](RECOVERY.md).

## Forward direction

See [roadmap](ROADMAP.md); planned capabilities are not described as implemented architecture.
