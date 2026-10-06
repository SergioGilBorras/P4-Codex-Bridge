# Resource scheduler

`ResourceScheduler` is the technical resource queue for Codex work. Business priority and task selection remain with P4-Jira-Agent-Orchestrator. Queue ordering is FIFO by submission time and run ID; optional integer `resource_priority` sorts ahead of FIFO ties.

The SQLite registry persists queue metadata and pending prompts (up to 1 MiB UTF-8) in a separate payload table. Agent metadata is capped at 8 KiB and output schemas at 1 MiB. A prompt payload is deleted atomically when a run is claimed or cancelled; it is not included in `ps`, `inspect`, metrics or logs. SQLite is not encrypted by this component and `persist_pending_payload=false` is not implemented. On Windows the default state directory is under `%LOCALAPPDATA%\\p4-codex-bridge`; deployments using `P4_CODEX_BRIDGE_STATE_DIR` must choose a user-private directory. The bridge does not rewrite ACLs. Pending prompt content therefore remains a local-at-rest privacy risk until dispatch/cancel.

Claims use `BEGIN IMMEDIATE`, persist the run state and workspace lock together, then hand the payload to the owning manager. A claimed run is never replayed automatically after a crash: it is marked `LOST` because the remote outcome may be unknown. Unclaimed queue entries remain available after restart.

Waiting reasons include `GLOBAL_LIMIT`, `BACKEND_LIMIT`, `PROFILE_LIMIT`, `THREAD_LIMIT`, and `WORKSPACE_LOCK`; a workspace conflict includes `blocked_by_run_id`. Queue position uses the same priority/FIFO ordering.

`READ` runs can share a workspace. Any `WRITE` run excludes all other access modes for its canonical workspace. Distinct workspaces can run concurrently. Canonical paths are resolved existing directories and normalized with Windows case/separator rules.

Limits are typed by `RuntimeLimits` and persisted in the same SQLite state database. Current defaults are conservative starting values, not a P4 business policy. `set_runtime_limits()` updates future dispatches; lowering limits does not stop active work. The app-server backend remains serialized to the configured capability even if Codex later proves more concurrency.

## Current API boundary

The resident `CodexRuntimeManager.start_turn` submits and dispatches app-server work through this queue. `resources()`, `list_runs()`, `inspect()`, `cancel()` and `set_runtime_limits()` expose runtime scheduling state. CLI `resources` and `limits` inspect the shared state database; queued cancellation is supported there, while cancelling active work requires the owning manager.

For human UX inspection, run `python tests_py/scheduler_demo.py --state-dir <temporary-private-directory>`, then in another PowerShell set `$env:P4_CODEX_BRIDGE_STATE_DIR` to that directory and use `p4-codex ps --json`, `p4-codex inspect demo_write`, `p4-codex watch demo_write`, `p4-codex resources`, or `p4-codex cancel demo_global`. The fixture includes separate agents/tasks, a shared-workspace blocker and a global-slot waiter. It creates scheduler records and fake lifecycle events only; it never launches Codex and uses zero tokens.

`resource_priority` is a technical ordering input applied only after the caller submits work. It does not represent Jira or business priority.

Managed exec integration: `CodexBridge.start()` submits through this queue and launches a detached worker only after an atomic claim. App-server turns and managed exec runs share global/backend/profile capacity and workspace locks. Exec completion wakes the resident manager to reconsider app-server queue entries. Direct one-shot `CodexBridge.run()` intentionally bypasses the scheduler. `CodexBridge.recover_exec_runs()` reconciles worker identity and a matching, valid result file; otherwise it marks claimed work `LOST` and never replays it.
