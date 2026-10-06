# Codex app-server capability matrix

## Final pre-commit evidence snapshot

| Feature | CODEX_SUPPORT | BRIDGE_SUPPORT | OFFLINE_TESTED | REAL_TESTED |
|---|---|---|---|---|
| exec one-shot / structured output / output-last-message | Installed CLI flags discovered | Implemented | Yes, fake CLI | Structured output smoke PASS; one-shot Live Watch not applicable |
| exec resume / fork / review | Installed subcommands discovered | Implemented as separate exec operations | Yes, fake CLI | Not exercised in this validation |
| app-server turns and event streams | Local protocol schema observed | Implemented; resident manager experimental | Yes, fake protocol | Live Watch smoke PASS for one turn and lifecycle stream |
| app-server persistent queue | Supported by bridge manager | Implemented within shared manager | Yes, fake stress | One managed turn dispatched; contention not tested |
| exec queue through shared dispatcher | CLI supports exec | Implemented by managed `CodexBridge.start`; `run()` remains direct | Fake CLI integration test | No; structured smoke used direct one-shot `run()` |
| global/backend/profile limits | Bridge resource policy | Shared scheduler enforces global, backend and profile limits | Yes, cross-backend scheduler tests | No contention test |
| workspace READ/WRITE locks | Bridge resource policy | Shared namespace across scheduled app-server and exec work | Yes, cross-backend scheduler tests | No conflict test |
| cancel queued work | Bridge-local state | Implemented | Yes | No |
| unified cancel for active exec/app-server | Backend mechanisms differ | Implemented through owning backend; OS fallback remains controlled | Backend tests only | No |
| watch / inspect / ps | Local registry/events | Implemented with partial replay | Yes | Live Watch smoke PASS; `ps`/`inspect` verified after run |
| recovery | Local process and scheduler metadata | Partial; claimed unknown work becomes LOST, never auto-replayed | Yes, fake recovery | No |
| approvals | App-server protocol | Manual approve/reject | Yes, fake protocol | No approval smoke run |
| MCP / skills / AGENTS child behavior | Codex configuration may expose them | Diagnostic discovery; child visibility/effective-for-run unconfirmed | Resolution logic only | Not confirmed |

Managed exec and app-server turns share the atomic SQLite scheduler, limits,
queue and workspace-lock namespace. Direct one-shot `run()` intentionally
bypasses scheduling. Cross-backend contention and active cancellation remain
offline-tested, not real-tested.

The development-session MCP/skill catalog does not establish child visibility.
No child-context smoke was run in this closeout.

## Live discovery exposure

| Capability | CODEX_SUPPORT | BRIDGE_SUPPORT | OFFLINE_TESTED | REAL_TESTED |
|---|---|---|---|---|
| Bridge run ID before execution | Bridge-local identity | IMPLEMENTED for exec and app-server turn handles | YES | YES, one app-server turn in Live Watch smoke |
| Native ID resolution | Exec thread ID JSONL; app-server thread/turn IDs | IMPLEMENTED; ambiguity errors | YES | NO |
| PS filters / inspect | Registry-local capability | IMPLEMENTED for bridge registry contents | YES | YES, active `ps` and post-run `inspect` |
| Read-only watch | Exec JSONL and app-server event streams exist | PARTIAL: independent SQLite polling; bounded sanitized lifecycle/message/tool records | YES | YES, one app-server turn |
| Multiple watchers / disconnect | Local journal allows independent reads | IMPLEMENTED; watcher never signals producer | YES | NO |
| Replay after restart | Only persisted events can be replayed | PARTIAL; deltas absent if backend did not persist them, `event_replay_complete=false` | YES | NO |
| Attach | No safe official read-only attach method confirmed | NOT_SUPPORTED; resume remains an operation, not attach | N/A | NO |

## Phase 5 runtime manager exposure

Audited against locally installed Codex CLI 0.160.1 and its generated experimental
v2 schema. OpenAI Developer Docs MCP was not callable in this turn.

| Feature | CODEX_SUPPORT | BRIDGE_SUPPORT | OFFLINE_TESTED | REAL_TESTED | CHILD_VISIBLE | EFFECTIVE_FOR_RUN |
|---|---|---|---|---|---|---|
| Resident owned stdio server | app-server experimental, local help/schema | PARTIAL: `CodexRuntimeManager.start/stop/restart`, one manager process | YES, fake protocol | NO | N/A | Only while manager health is HEALTHY |
| Shared manager/multiple threads | `thread/start`, persistent threads in schema | PARTIAL: multiple threads through one reader/connection | YES, fake protocol; limit configuration exercised | NO | N/A | Thread creation confirmed only against successful request |
| Multiple turns/concurrency queue | `turn/start`; protocol does not establish unlimited concurrency | Shared persistent scheduler for app-server turns and managed exec runs | YES, scheduler stress and fake exec | NO | N/A | Direct one-shot `run()` bypasses resource scheduling |
| Health/metrics | initialize handshake and process state | IMPLEMENTED locally; protocol responsive is represented by successful startup, no periodic probe | YES | NO | N/A | Local process and DB state only |
| Recovery/reconnect | `thread/resume` and `thread/turns/list` exist in local schema | PARTIAL: SQLite records lifecycle and reports unknown in-flight work; no auto-resume or delta replay | YES, dry-run reconciliation | NO | N/A | No turn is re-executed |
| Lock/singleton | OS file lock behavior | IMPLEMENTED using OS advisory lock; process identity not sufficient for remote child re-adoption, which is unsupported | YES, competing manager fake | NO | N/A | One local lock path |
| Version/capability gates | handshake exposes protocol/server info | PARTIAL: reports handshake; no full local CLI capability negotiation/gates yet | YES, static manager response | NO | N/A | Unknown features remain unknown |
| Approval RPC in runtime manager | app-server can request command/file/permission approvals | NOT_SUPPORTED in manager; replies with method-not-handled error and persists a sanitized lifecycle error. Existing per-turn `CodexBridge` approval API remains available | YES, protocol behavior covered by prior fake app-server suite; manager fail-closed path not yet dedicated-tested | NO | N/A | Never auto-approves; use existing per-turn API for approvals |
| Exec run recovery | CLI process can outlive bridge in some failure modes | NOT_SUPPORTED: no safe exec worker re-adoption | N/A | NO | N/A | None |

Do not interpret Codex support as bridge support. The daemon/proxy is not used;
this manager owns a `stdio://` child, avoiding assumptions about socket support
on Windows.

## Phase 4: installed CLI and bridge exposure

Audited on the installed `codex-cli 0.160.0` using local `--help` and generated app-server v2 schemas. OpenAI Developer Docs MCP was registered/enabled according to the global CLI inventory, but was **not callable from this agent turn**; official web docs were used only as secondary context. Run-local facts take precedence.

The states in the last two columns refer to child/run behavior and are deliberately not inferred from the current development-session MCP inventory.

| Capability | CODEX_SUPPORT | BRIDGE_SUPPORT | OFFLINE_TESTED | REAL_TESTED | CHILD_VISIBLE | EFFECTIVE_FOR_RUN |
|---|---|---|---|---|---|---|
| `exec resume` | YES: local subcommand help | IMPLEMENTED: `CodexBridge.resume`; distinct from app-server thread resume | YES, fake CLI | NO | Not queried by operation | Stored session context/policy is used; no separate sandbox/approval override |
| `exec fork` | YES: local subcommand help | IMPLEMENTED: `CodexBridge.fork`; returned thread ID parsed from JSONL when emitted | YES, fake CLI | NO | Not queried by operation | Fork semantics beyond CLI output are not independently verified |
| `exec review` | YES: local subcommand help; `--uncommitted`, `--base`, `--commit`, `--title` observed | IMPLEMENTED for those three targets | YES, fake CLI | NO | N/A | Target is read from the child working tree; no arbitrary file target |
| Structured output | YES: `--output-schema` | IMPLEMENTED; `RunResult.structured_output`, `text_output`, optional `raw_output` | YES, fake CLI | NO | N/A | Invalid JSON fails; no silent repair or full JSON Schema validation by bridge |
| Final message file | YES: `--output-last-message` | IMPLEMENTED using a private temp file and cleanup | YES, fake CLI incl. missing/malformed/timeout | NO | N/A | File is authoritative when requested |
| Model / model catalog | `--model`; app-server `model/list` | IMPLEMENTED; catalog is dynamic, not entitlement | YES, fake app-server | NO in Phase 4 | Per child config/run | Explicit model is passed; otherwise Codex config/default applies |
| Reasoning effort | `-c model_reasoning_effort`; model schema advertises values per model | IMPLEMENTED as string validated against CLI-safe syntax; use `list_models()` for advertised values | YES, fake CLI | NO | Config-dependent | Per-run explicit setting where provided |
| Reasoning summary | Config schema: `auto`, `concise`, `detailed`, `none` | IMPLEMENTED with enum | YES, fake CLI | NO | Config-dependent | Per-run explicit setting where provided |
| Verbosity | Config schema: `low`, `medium`, `high` | IMPLEMENTED with enum | YES, fake CLI | NO | Config-dependent | Per-run explicit setting where provided |
| Exec sandbox / approvals | Sandbox `read-only`, `workspace-write`, `danger-full-access`; approval `never`, `on-request` | IMPLEMENTED for one-shot `run`; defaults remain read-only/never | YES, fake CLI | Existing Phase 1 smoke only; not re-run | Passed as child args | Explicit profile/permissions for new run |
| Writable roots / network | `--add-dir`; config schema includes workspace-write `writable_roots` and `network_access` | PARTIAL: run roots use validated `--add-dir`; workspace-write network config defaults false and can be explicitly enabled. App-server has typed controls | YES, fake argv/app-server | NO in Phase 4 | Passed only when configured | Does not control network use by MCP tools independently |
| Config policy | `--ignore-user-config`, cwd and `-c` observed | IMPLEMENTED: `isolated`, `project`, `explicit`; user-only rejected | YES, fake CLI | NO Phase 4 | Config layers are child-specific | Isolated ignores user config flag only; project config/AGENTS/skills behavior not inferred |
| Effective config | app-server `config/read` with layers/origins | IMPLEMENTED credential-filtered field whitelist | YES, fake app-server fixtures | NO | Visible to a diagnostic app-server child | Describes diagnostic child config, not a matching `exec` run |
| MCP inventory | app-server `mcpServerStatus/list` | PARTIAL diagnostic listing; names/status/tool descriptors, no invocation | YES, parser/policy fixtures | NO | `diagnostic_app_server` only | NOT_CONFIRMED for exec run; no per-run MCP allowlist enforcement |
| Skills inventory | app-server `skills/list` scoped by cwd | PARTIAL diagnostic listing | YES, fixtures | NO | `diagnostic_app_server` only | NOT_CONFIRMED for exec run |
| AGENTS.md | Official Codex project behavior is documented; exact local policy interaction not established | No run-level loaded-file receipt | Fixture/script added; manual only | NO Phase 4 | NOT_CONFIRMED until marker smoke | NOT_CONFIRMED per policy until exact marker response |
| Development-session MCPs (`codex_apps`, `codex_tui`, `pycharm`, `serena`, `openaideveloperdocs`) | Current host/session inventory only | No inherited capability assumed | N/A | NO child test | SESSION_VISIBLE is session-dependent; CHILD_VISIBLE unknown | EFFECTIVE_FOR_RUN unknown; Docs MCP not runtime dependency |

### Config policy boundaries

| Policy | Layers used | Limits / precedence |
|---|---|---|
| `isolated` | CLI adds `--ignore-user-config`; runtime settings still supplied explicitly | Does not prove project config, `AGENTS.md`, skills or MCP are suppressed. Do not call it fully isolated. |
| `project` | Native Codex configuration resolved for the child process cwd, including applicable user/project layers | Project trust can affect project config. Native layering is Codex-owned. |
| `explicit` | Same native layers as `project`, then allowlisted session `-c` overrides | Explicit typed values / `-c` take precedence over file layers. No arbitrary flags/config keys. |
| user-only | Not selectable through observed exec interface | Rejected by API. |

`get_effective_config`, `list_configured_mcps`, and `list_effective_skills` start a short-lived **diagnostic app-server child**. Their visibility does not prove that a separate `codex exec` child sees or uses the same capability. `get_effective_capabilities()` keeps run-level fields unknown until a matching execution can be observed. MCP status `connected` plus tool names means advertised by the diagnostic server; it does not prove a tool call is callable. Session tool inventory also changes dynamically between turns.

Audited against the **installed Codex CLI 0.160.0**. The local source of truth was generated by `codex app-server generate-json-schema --out <dir> --experimental`; the app-server command itself reports `[experimental]`. JSON-RPC uses `stdio://` for the Bridge implementation. This matrix describes the installed protocol, not every capability implemented by P4-Codex-Bridge.

The upstream protocol evolves quickly. Compare the local schema generated by the installed binary before relying on a method. See OpenAI's [app-server overview](https://developers.openai.com/blog/codex-as-a-platform) and [protocol definitions](https://github.com/openai/codex/tree/main/codex-rs/app-server-protocol).

## Server notifications

All names below are exact `method` values present in the installed notification schema.

| Area | Methods |
|---|---|
| Errors and warnings | `error`, `warning`, `guardianWarning`, `deprecationNotice`, `configWarning`, `windows/worldWritableWarning`, `windowsSandbox/setupCompleted` |
| Thread lifecycle/state | `thread/started`, `thread/status/changed`, `thread/archived`, `thread/deleted`, `thread/unarchived`, `thread/closed`, `thread/reverted`, `thread/name/updated`, `thread/attachment/updated`, `thread/goal/updated`, `thread/goal/cleared`, `thread/compacted`, `thread/queue/changed`, `thread/project/updated`, `thread/environment/connected`, `thread/environment/disconnected`, `thread/settings/updated`, `thread/tokenUsage/updated` |
| Turn lifecycle/plans | `turn/started`, `turn/completed`, `turn/diff/updated`, `turn/plan/updated`, `turn/moderationMetadata`, `hook/started`, `hook/completed` |
| Items and text | `item/started`, `item/completed`, `item/agentMessage/delta`, `item/plan/delta`, `item/reasoning/summaryTextDelta`, `item/reasoning/summaryPartAdded`, `item/reasoning/textDelta`, `rawResponseItem/completed`, `rawResponse/completed`, `item/autoApprovalReview/started`, `item/autoApprovalReview/completed`, `autoApprovalReview/strictReviewRequired` |
| Command/process activity | `command/exec/outputDelta`, `process/outputDelta`, `process/exited`, `item/commandExecution/outputDelta`, `item/commandExecution/terminalInteraction`, `item/fileChange/outputDelta`, `item/fileChange/patchUpdated` |
| Request/MCP/plugin activity | `serverRequest/resolved`, `item/mcpToolCall/progress`, `mcpServer/oauthLogin/completed`, `mcpServer/startupStatus/updated`, `mcpServer/event/stream/notification`, `app/list/updated`, `skills/changed` |
| Account/provider/model | `account/updated`, `account/gatewayOAuth/changed`, `account/rateLimits/updated`, `account/login/completed`, `model/rerouted`, `model/verification`, `model/safetyBuffering/updated`, `modelProvider/authRecoveryStarted`, `modelProvider/authRecoveryCompleted` |
| Project/config/filesystem/search | `project/changed`, `externalAgentConfig/import/progress`, `externalAgentConfig/import/completed`, `fs/changed`, `fuzzyFileSearch/sessionUpdated`, `fuzzyFileSearch/sessionCompleted` |
| Remote/realtime | `remoteControl/status/changed`, `thread/realtime/started`, `thread/realtime/itemAdded`, `thread/realtime/item/started`, `thread/realtime/item/transcript/delta`, `thread/realtime/item/completed`, `thread/realtime/transcript/delta`, `thread/realtime/transcript/done`, `thread/realtime/outputAudio/delta`, `thread/realtime/sdp`, `thread/realtime/error`, `thread/realtime/closed` |

## Server-initiated requests and client response methods

Requests requiring a client JSON-RPC response are distinct from notifications:

| Request method | Request fields verified in schema | Response shape / bridge handling |
|---|---|---|
| `item/commandExecution/requestApproval` | JSON-RPC `id`; `itemId`, `startedAtMs`, `threadId`, `turnId`; optional `approvalId`, `command`, `commandActions`, `cwd`, `reason`, permission/network context and decisions | `{decision: accept\|acceptForSession\|decline\|cancel}` and additional schema-defined decisions. Bridge exposes `accept` and `decline`; manual by default. |
| `item/fileChange/requestApproval` | JSON-RPC `id`; `itemId`, `startedAtMs`, `threadId`, `turnId`; optional `grantRoot`, `reason` | `{decision: accept\|acceptForSession\|decline\|cancel}`. Bridge exposes `accept` and `decline`. |
| `item/permissions/requestApproval` | JSON-RPC `id`; `cwd`, `itemId`, `permissions`, `startedAtMs`, `threadId`, `turnId`; optional `environmentId`, `reason` | Response requires `permissions`; Bridge rejects with `permissions: null`. Accepting returns the requested permission structure. |
| `item/tool/requestUserInput` | `threadId`, `turnId`, `itemId`, questions | Not an approval. Bridge returns JSON-RPC method-not-handled error and emits `ServerError`. |
| `mcpServer/elicitation/request` | `threadId`, `turnId`, server, mode, message, requested schema | Not auto-approved; currently returns unsupported-method error and emits `ServerError`. |
| `item/tool/call`, `account/chatgptAuthTokens/refresh`, `attestation/generate`, `currentTime/read`, legacy `applyPatchApproval`, `execCommandApproval` | Version/schema-specific request payload | Not implemented by the Bridge; unsupported methods receive a JSON-RPC error. No auth token refresh/copying is performed. |

Client RPC methods include `initialize`, `thread/start`, `thread/resume`, `thread/fork`, `thread/unsubscribe`, `thread/read`, `thread/turns/list`, `thread/items/list`, `turn/start`, `turn/steer`, `turn/interrupt`, `model/list`, `review/start`, configuration/MCP/skills/plugin/filesystem operations, command/process operations and realtime operations. The Bridge currently calls `initialize`, `thread/start`, `turn/start`, and `turn/interrupt`; model discovery already calls `model/list`. The generated schema includes the exact remaining method names.

## Bridge exposure

| Capability | State |
|---|---|
| Sync `CodexBridge.stream_events()` / live `start_turn()` | IMPLEMENTED; one app-server process and one turn per handle |
| Server-wide sync `stream_all_events()` | IMPLEMENTED for live handles owned by one `CodexBridge` instance; ends when observed turns finish or its timeout expires |
| Async `astream_events()` / `astream_all_events()` | IMPLEMENTED; same synchronous reader and queues underneath |
| `thread/started`, `turn/started`, message deltas/completion, tools, approvals, turn completion/failure/interruption, protocol errors | IMPLEMENTED normalization where the installed notifications expose them |
| Unknown notifications | Preserved as `UnknownEvent` with optional sanitized `raw_event` |
| `turn/interrupt` | IMPLEMENTED against a live handle |
| Persistent thread resume, fork, send/steer | PLANNED |
| Resident multi-thread runtime manager | IMPLEMENTED locally; app-server remains experimental |
| Tool/user-input and MCP elicitation request handling | PARTIAL; surfaced as `ServerError` and declined at JSON-RPC method level |
| App-server reconnect/replay of transient deltas | PLANNED; only lifecycle events are persisted for replay |

The upstream [Python SDK client implementation](https://github.com/openai/codex/blob/main/sdk/python/src/openai_codex/client.py) is a useful reference, but the package is not installed as a runtime dependency here.

## MCP inventory and effective capability states

This is a development-session inventory, not a claim about the environment inherited by a Codex subprocess. See [`TOOLS_CATALOG.md`](TOOLS_CATALOG.md) for definitions, profile posture and per-MCP details.

| MCP namespace | Session inventory | Configured | Enabled | Callable in this turn | Auth status | Child-visible | Effective for a bridge run |
|---|---:|---|---|---|---|---|
| `codex_apps` | 89 reported; 73 definitions visible to this agent | Unknown (Codex Apps host) | Exposed by host | 73 definitions exposed; 89-count inventory not callable here | Unknown | Unknown | Unknown |
| `codex_tui` | 9 | Unknown (Codex TUI host) | Exposed by host | Yes, nine tools | Unknown | Unknown | Unknown |
| `openaideveloperdocs` | 5 reported; no callable definitions exposed to this agent | Yes, global `codex mcp list` entry | Yes, `enabled` | Not confirmed; harmless tool call unavailable in this turn | `Unknown` from CLI | Unknown | Unknown |
| `pycharm` | 37 | Yes, global CLI entry observed | Exposed by host | Yes, 37 tools | `Unsupported` from CLI | Unknown | Unknown; current IDE project differs from this checkout |
| `serena` | 23 | Yes, global CLI entry observed | Exposed by host | Yes, 23 tools | `Unsupported` from CLI | Unknown | Unknown |

The session tool inventory currently available to this agent does not match all counts reported for the session: it exposes 73 `codex_apps` definitions, and no `openaideveloperdocs` definitions, while the supplied inventory reports 89 and 5 respectively. This difference is preserved rather than assuming deferred/unseen tools are callable. The OpenAI Docs MCP is registered and enabled globally, auth status is `Unknown`, but its callability was not verified. An official web search found [OpenAI Docs MCP guidance](https://developers.openai.com/learn/docs-mcp); this is not an MCP invocation.

### State semantics

- `SESSION_VISIBLE`: MCP/tool descriptors are present in the current agent session.
- `CONFIGURED`: a config entry exists in a named scope; this alone does not prove reachability.
- `ENABLED`: the host/config does not disable it; this alone does not prove invocation works.
- `CALLABLE`: an invocation schema/tool is exposed to this agent; confirm with a harmless request where possible.
- `CHILD_VISIBLE`: the launched Codex CLI/app-server child reports the MCP/tool during that run.
- `EFFECTIVE_FOR_RUN`: evidence shows the selected bridge run loaded or called the MCP. Do not infer this from session visibility or Codex config alone.
- Record unsupported/unobserved values as `unknown`, not `false`, and never compress these states into one `available` property.

### TUI and external-integration boundaries

Codex TUI tools (`create_thread`, `fork_thread`, `list_archived_threads`, `list_threads`, `read_thread`, `send_message_to_thread`, `set_thread_archived`, `set_thread_title`, `wait_threads`) are host-session thread operations. They are separate from app-server JSON-RPC; child visibility is unconfirmed. Bridge lifecycle should remain on official CLI/app-server APIs and must not require TUI MCP.

Codex Apps includes potentially powerful external integrations such as Atlassian/Jira reads and writes, Jira transitions, destructive actions, plugin management, Sites/deployment and document operations. Session visibility does not grant bridge profiles access. The desired policy is deny-by-default for external/destructive capabilities, with `analysis` no external side effects, `planning` read-oriented, `implementation` explicit opt-in and `validation` minimum required. The installed exec interface has no per-run MCP/tool allowlist, so this policy is **PARTIAL / not fully enforceable**; avoid untrusted project MCP configurations. `list_configured_mcps()` and `list_effective_skills()` provide diagnostic-child listings, and `get_effective_capabilities()` preserves unknown run-level states. Category controls and exact exec-run effectiveness remain unconfirmed. The docs MCP is for development verification and is not a bridge runtime dependency.
# Runtime scheduling

| Capability | Codex support | Bridge support | Offline tested | Real tested |
|---|---|---|---|---|
| Persistent queue and atomic claims | N/A (bridge-local) | IMPLEMENTED | YES | NO |
| App-server slot limits | Protocol-driven | IMPLEMENTED | Fake app-server + scheduler | NO |
| Exec process slot scheduling | CLI supports managed runs | IMPLEMENTED by `CodexBridge.start`; `run()` remains one-shot | YES, fake CLI | NO |
| Workspace READ/WRITE locks | N/A (bridge-local) | IMPLEMENTED | YES, including 50-job fake stress | NO |
| Queue recovery | N/A (bridge-local) | IMPLEMENTED; unclaimed work restored, claimed work becomes LOST | YES | NO |
| Active run cancellation through CLI | Backend-dependent | IMPLEMENTED for scheduled exec; app-server routed to owner | YES, fake coverage | NO |
