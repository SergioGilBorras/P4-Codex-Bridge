# Codex app-server capability matrix

## Current 1.0 software closeout snapshot (2026-10-07)

Schema source vocabulary: `AUTHORITATIVE_LOCAL_SCHEMA`, `GENERATED_LOCAL_SCHEMA`,
`RUNTIME_INTROSPECTION`, `DOCUMENTATION_ONLY`, `NOT_AVAILABLE`. The current
Python package uses the installed generated local JSON schema; a snapshot
contains version (when the local version probe succeeds), source type, content
hash, discovered RPC methods, generation timestamp and parser version. It does
not retain the full generated schemas. Schema evidence alone is limited;
initialize is confirmed by handshake and individual RPCs are confirmed only
after successful runtime responses.

| Area | Classification | Evidence / boundary |
|---|---|---|
| Project trust and run security gate | IMPLEMENTED | Typed gate is exercised by direct exec, managed exec, runtime manager and cross-process/daemon tests; unknown MCP state rejects. Trusted acknowledged external side-effect risk is an explicit unfiltered opt-in with warning. |
| Per-run MCP isolation | NOT_SUPPORTED / KNOWN_LIMITATION | Codex 0.160.1 surface has no verified per-run allow/deny filter or empty-MCP receipt. Classified `NOT_SUPPORTED_BY_CODEX` and `SECURITY_BOUNDARY_DOCUMENTED`; non-blocking while every execution route remains gated. |
| App-server schema mechanism | IMPLEMENTED / GENERATED_LOCAL_SCHEMA verified | Installed `@openai/codex` 0.160.1 exposes `app-server generate-json-schema`; preflight completed locally on 2026-10-07. Compact snapshot SHA-256 `4a02439823bc98fbbca86d9f934d5a90a638b41ec16c635c8c4448b2b9e14867`, 262 literal protocol method names. This verifies schema generation, not that every method was accepted by a live runtime. |
| App-server feature preflight | IMPLEMENTED with limitations | Explicit bridge capability→RPC mapping; schema presence yields `SUPPORTED_WITH_LIMITATIONS`, successful runtime method response promotes only that method, method-not-found/known missing schema is negative evidence, absent/corrupt schema remains UNKNOWN. |
| Required service startup preflight | IMPLEMENTED | Requires local schema evidence for `thread/start`, `turn/start` and successful JSON-RPC initialize before dispatch. UNKNOWN/unsupported prevents app-server startup; exec remains independent. |
| Structured output over app-server | UNKNOWN | The installed generated schema did not let the bridge associate `outputSchema` with `turn/start`; the bridge does not claim this app-server capability. Exec `--output-schema` is a separate verified CLI capability. |
| Python package-root exports | FROZEN candidate | Exact allowlist test; `CodexRuntimeManager`, SQLite, scheduler, registry, transport and worker internals stay unexported. `CodexBridge.run` now has a closed explicit signature. |
| CLI JSON stdout contract | FROZEN candidate | Frozen parser tree and exit map are covered by tests. Finite results emit JSON; stream commands emit JSONL; foreground service logs go to stderr. |
| Configuration validation | FROZEN candidate | Strict TOML section/key schema, exact prefixed environment names and CLI > environment > TOML > defaults where applicable; no `config_version`, unknown fields fail fast. |
| JavaScript runtime | REMOVED | ADR-002 records the Python-only decision. Consumer JS sources outside this repository were not changed. |

The table above is the current closeout status. Historical phase tables below
record evidence at the time and do not override this snapshot. No inference was
run during this closeout.

> **Canonical audit:** use the classification table near the end of this file
> for release status. Earlier phase snapshots are retained as historical test
> evidence; their local `IMPLEMENTED/PARTIAL/PLANNED` labels are not the final
> 1.0 classification by themselves.

## Final pre-commit evidence snapshot

| Feature | CODEX_SUPPORT | BRIDGE_SUPPORT | OFFLINE_TESTED | REAL_TESTED |
|---|---|---|---|---|
| exec one-shot / structured output / output-last-message | Installed CLI flags discovered | Implemented | Yes, fake CLI | Structured output smoke PASS; one-shot Live Watch not applicable |
| exec resume / fork / review | Installed subcommands discovered | Implemented as separate exec operations | Yes, fake CLI | Not exercised in this validation |
| app-server turns and event streams | Local protocol schema observed | Implemented; resident manager experimental | Yes, fake protocol | Live Watch smoke PASS for one turn and lifecycle stream |
| app-server persistent queue | Supported by bridge manager | Implemented within shared manager | Yes, fake stress | Three sequential turns dispatched on a resumed and forked thread; contention not tested |
| exec queue through shared dispatcher | CLI supports exec | Implemented by managed `CodexBridge.start`; `run()` remains direct | Fake CLI integration test | No; structured smoke used direct one-shot `run()` |
| global/backend/profile limits | Bridge resource policy | Shared scheduler enforces global, backend and profile limits | Yes, cross-backend scheduler tests | No contention test |
| workspace READ/WRITE locks | Bridge resource policy | Shared namespace across scheduled app-server and exec work | Yes, cross-backend scheduler tests | No conflict test |
| cancel queued work | Bridge-local state | Implemented | Yes | No |
| unified cancel for active exec/app-server | Backend mechanisms differ | Implemented through owning backend; OS fallback remains controlled | Backend tests only | No |
| watch / inspect / ps | Local registry/events | Implemented with partial replay | Yes | Live Watch smoke PASS; `ps`/`inspect` verified after run |
| recovery | Local process and scheduler metadata | Partial; claimed unknown work becomes LOST, never auto-replayed | Yes, fake recovery | No |
| approvals | App-server protocol | Manual approve/reject; no automatic approval | Yes, fake protocol | Approval request observed as pending, turn reached `WAITING_APPROVAL`, explicit reject resolved it; approval/target not created |
| MCP / skills / AGENTS effective behavior | Installed config/app-server discovery plus OpenAI Docs | Diagnostic APIs implemented; per-run MCP filtering not implemented | Yes, fake config/MCP/skills fixtures | No real model turns in this phase |

Managed exec and app-server turns share the atomic SQLite scheduler, limits,
queue and workspace-lock namespace. Direct one-shot `run()` intentionally
bypasses scheduling. Cross-backend contention and active cancellation remain
offline-tested, not real-tested.

The development-session MCP/skill catalog does not establish child visibility.
No child-context model smoke was run in this phase because the diagnostic app-server
advertised external write/deploy/destructive tools and the CLI has no verified
per-run MCP filter. No run-level AGENTS, skill, or tool callability receipt exists.

## Phase 7: MCP / skills / AGENTS effective behavior (2026-10-06)

| Capability | CODEX_SUPPORT | BRIDGE_SUPPORT | OFFLINE_TESTED | REAL_TESTED | CHILD_VISIBLE | EFFECTIVE_FOR_RUN |
|---|---|---|---|---|---|---|
| Host MCP snapshot | Current session tool catalog | Snapshot documented, not runtime API | N/A | Host Docs MCP harmless query succeeded | Host only | N/A |
| CLI configured MCP inventory | `codex mcp list` | Diagnostic CLI evidence documented | N/A | CLI list observed | Serena, PyCharm, Docs configured/enabled globally | Not run-specific |
| Diagnostic app-server MCP inventory | `mcpServerStatus/list` | `list_configured_mcps`; advertised names/schema only | Yes, fake protocol | Yes, diagnostic only; Apps 89, Docs 5; Serena/PyCharm handshake failed | Confirmed only for short-lived diagnostic app-server | NOT_CONFIRMED for `exec` |
| MCP tool invocation from child | Protocol advertises tool descriptions | No bridge invocation/effectiveness receipt | Fake status fixtures only | No tools invoked | NOT_CONFIRMED for `exec`; no Apps writes attempted | NOT_CONFIRMED |
| Host skills snapshot | Session supplied 18 skills | Documentation snapshot only | N/A | Host supplied catalog | Host only | N/A |
| Diagnostic `skills/list` | Installed app-server schema | `list_effective_skills`; listing only | Yes | Yes, diagnostic only: 5 enabled `system` entries | Confirmed only for diagnostic app-server | NOT_CONFIRMED for `exec` |
| Skills selected by `exec` | Official docs describe progressive disclosure and skill locations | No selection receipt exposed | Fixture/list parser only | No | NOT_CONFIRMED | NOT_CONFIRMED |
| AGENTS root/nested precedence | Official docs describe guidance layers and nearer-file precedence | No loaded-file receipt; marker script exists | No model-free proof | No | NOT_CONFIRMED | NOT_CONFIRMED |
| Project `.codex/config.toml` trust | Official config reference says project config loads only for trusted projects | `config/read` diagnostic, filtered sources | Yes, fake layer fixtures | Fixture diagnostic had user/system layers and no project layer | Diagnostic only | Exact run trust/effect NOT_CONFIRMED |
| Per-run MCP allow/deny | No `codex exec` allowlist observed in local help | NOT_SUPPORTED by current Bridge | N/A | N/A | N/A | NOT_SUPPORTED |
| Luna model | `model/list` listed `gpt-6-luna` | `list_models()` discovery | N/A | No inference; entitlement not tested | Catalog response only | NOT_CONFIRMED |

The harmless documentation queries consume no model turns. No real inference was
performed; there is no token usage or latency for this phase. `gpt-6-luna` was the
exact installed `model/list` ID matching OpenAI Docs' GPT-6 Luna name. Listing the
ID does not prove account entitlement.

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
v2 schema. OpenAI Developer Docs MCP was callable for official app-server method
semantics; the generated local schema remains the installed-version authority.

| Feature | CODEX_SUPPORT | BRIDGE_SUPPORT | OFFLINE_TESTED | REAL_TESTED | CHILD_VISIBLE | EFFECTIVE_FOR_RUN |
|---|---|---|---|---|---|---|
| Persistent thread resume | YES: installed experimental `thread/resume` schema | IMPLEMENTED in `CodexRuntimeManager.resume_thread`; verifies returned native ID; distinct from `CodexBridge.resume` (`codex exec resume`) | YES, fake JSON-RPC incl. restart | YES: same ID resumed; next turn recalled marker from prior turn | N/A | Explicit resume reopens context; it does not resume a previous turn |
| Persistent thread fork | YES: installed experimental `thread/fork` schema | IMPLEMENTED in `fork_thread`; native fork RPC, parent relation persisted, `lastTurnId`/`beforeTurnId` exclusive | YES, fake JSON-RPC | YES: fork had a new ID and parent link; fork turn recalled inherited marker | N/A | Uses server-forked history; ephemeral fork is not resumable |
| Turn steer | YES: installed experimental `turn/steer`; requires `expectedTurnId`, `input`, `threadId` | IMPLEMENTED as `steer_turn`; active RUNNING turn only | YES, fake JSON-RPC | NO | N/A | Appends input to that active turn; not equivalent to a new turn |
| Turn status reconciliation | YES: `thread/turns/list`; turn statuses completed/failed/interrupted/inProgress | PARTIAL: on explicit resume, one page up to 100 reconciles matching terminal turn IDs; active turns are not adopted | YES, fake restart/reconciliation | NO | N/A | No automatic reexecution; older/missing IDs remain unknown |
| Runtime-manager approvals | YES: command/file/permissions approval JSON-RPC requests | IMPLEMENTED: central reader, persistent server-bound decisions, WAITING_APPROVAL, CLI/Python manual resolution, timeout decline | YES, fake protocol including restart-stale and timeout | YES: file-write request listed pending, `WAITING_APPROVAL`, explicit reject resolved; no file created | N/A | Only the live owning server instance can answer; restart marks stale |
| Transport reconnection | app-server stdio can be restarted locally | PARTIAL: explicit manager `restart()` creates a new transport; threads then require explicit resume | YES, fake manager restart | NO | N/A | No automatic reconnect loop or active-turn adoption |
| Lifecycle replay / remote deltas | Local DB can retain lifecycle events; no remote delta replay method confirmed | PARTIAL local lifecycle replay; resident-manager deltas/tool payloads are not persisted | YES, fake journal/restart | NO | N/A | `replay_complete=false`; no claim of complete stream replay |
| Resident owned stdio server | app-server experimental, local help/schema | PARTIAL: `CodexRuntimeManager.start/stop/restart`, one manager process | YES, fake protocol | NO | N/A | Only while manager health is HEALTHY |
| Shared manager/multiple threads | `thread/start`, persistent threads in schema | PARTIAL: multiple threads through one reader/connection | YES, fake protocol; limit configuration exercised | NO | N/A | Thread creation confirmed only against successful request |
| Multiple turns/concurrency queue | `turn/start`; protocol does not establish unlimited concurrency | Shared persistent scheduler for app-server turns and managed exec runs | YES, scheduler stress and fake exec | NO | N/A | Direct one-shot `run()` bypasses resource scheduling |
| Health/metrics | initialize handshake and process state | IMPLEMENTED locally; protocol responsive is represented by successful startup, no periodic probe | YES | NO | N/A | Local process and DB state only |
| Recovery/reconnect | `thread/resume` and `thread/turns/list` exist in local schema | PARTIAL: explicit resume verifies threads and reconciles matching terminal turns; no auto-resume, active-turn adoption, or delta replay | YES, fake restart/reconciliation | NO | N/A | No turn is re-executed |
| Lock/singleton | OS file lock behavior | IMPLEMENTED using OS advisory lock; process identity not sufficient for remote child re-adoption, which is unsupported | YES, competing manager fake | NO | N/A | One local lock path |
| Version/capability gates | handshake exposes protocol/server info | PARTIAL: reports handshake; no full local CLI capability negotiation/gates yet | YES, static manager response | NO | N/A | Unknown features remain unknown |
| Approval RPC in runtime manager | app-server can request command/file/permission approvals | IMPLEMENTED manually through manager-owned request IDs; stale approvals are not resolved after restart | YES, fake protocol | NO | N/A | Manual decision only; timeout decline; never auto-approves |
| Exec run recovery | CLI process can outlive bridge in some failure modes | NOT_SUPPORTED: no safe exec worker re-adoption | N/A | NO | N/A | None |

Do not interpret Codex support as bridge support. The daemon/proxy is not used;
this manager owns a `stdio://` child, avoiding assumptions about socket support
on Windows.

## Phase 4: installed CLI and bridge exposure

Historical Phase 4 audit: installed `codex-cli 0.160.0`, local `--help` and generated app-server v2 schemas. OpenAI Developer Docs MCP was not callable in that earlier agent turn, so official web docs were secondary context. In the Phase 7 session on 2026-10-06, the Docs MCP was callable for harmless documentation queries. Run-local facts take precedence, and host callability does not imply child visibility.

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

Client RPC methods include `initialize`, `thread/start`, `thread/resume`, `thread/fork`, `thread/unsubscribe`, `thread/read`, `thread/turns/list`, `thread/items/list`, `turn/start`, `turn/steer`, `turn/interrupt`, `model/list`, `review/start`, configuration/MCP/skills/plugin/filesystem operations, command/process operations and realtime operations. The runtime manager calls `thread/start`, `thread/resume`, `thread/fork`, `thread/turns/list`, `turn/start`, `turn/steer`, and `turn/interrupt`; it handles the three schema-confirmed approval request methods. Model discovery also calls `model/list`.

## Bridge exposure

| Capability | State |
|---|---|
| Sync `CodexBridge.stream_events()` / live `start_turn()` | IMPLEMENTED; one app-server process and one turn per handle |
| Server-wide sync `stream_all_events()` | IMPLEMENTED for live handles owned by one `CodexBridge` instance; ends when observed turns finish or its timeout expires |
| Async `astream_events()` / `astream_all_events()` | IMPLEMENTED; same synchronous reader and queues underneath |
| `thread/started`, `turn/started`, message deltas/completion, tools, approvals, turn completion/failure/interruption, protocol errors | IMPLEMENTED normalization where the installed notifications expose them |
| Unknown notifications | Preserved as `UnknownEvent` with optional sanitized `raw_event` |
| `turn/interrupt` | IMPLEMENTED against a live handle |
| Persistent thread resume / fork / turn steer | IMPLEMENTED experimentally through `CodexRuntimeManager`; see Phase 6 evidence rows |
| Resident multi-thread runtime manager | IMPLEMENTED locally; app-server remains experimental |
| Tool/user-input and MCP elicitation request handling | PARTIAL; surfaced as `ServerError` and declined at JSON-RPC method level |
| App-server reconnect/replay of transient deltas | PLANNED; only lifecycle events are persisted for replay |

## Final 1.0 audit classification

| Capability | Classification | Evidence / boundary |
|---|---|---|
| Python one-shot `exec` | IMPLEMENTED | Fake CLI, previous real structured-output and live-watch evidence |
| `exec resume`, `fork`, `review` | PARTIAL | Wrappers and fake tests; capability gate checks local subcommand help before launch; real behavior not exercised in final audit |
| Structured output and last-message capture | IMPLEMENTED | Fake CLI tests; structured-output real smoke previously passed |
| Persistent thread create/resume/fork and continuation | IMPLEMENTED | Fake protocol tests and previous real persistent-thread smoke |
| `turn/steer` | PARTIAL | Schema-confirmed and fake-tested; real execution intentionally not required due nondeterministic timing |
| Manual approvals and reject | IMPLEMENTED | Fake protocol lifecycle; prior real reject smoke passed |
| Approval accept | PARTIAL | Fake protocol coverage; no real accept smoke; never automatic |
| Shared exec/app-server queue, limits, locks and cancellation | IMPLEMENTED | Offline cross-backend tests/stress; real contention not tested |
| Conservative recovery and event replay | PARTIAL | Known lifecycle replay and terminal reconciliation; no delta replay, uncertain work remains LOST/UNKNOWN |
| Foreground daemon and SQLite control | IMPLEMENTED for foreground service | Fake lifecycle and typed cross-process submissions; final installed-wheel one-turn daemon smoke passed. Native Windows SCM integration is OUT_OF_SCOPE |
| Health/metrics | PARTIAL | Local snapshots and counters; DB integrity/retention added in this audit, full service-health fault matrix not yet rerun |
| Retention/maintenance | IMPLEMENTED for explicit maintenance | Dry-run/apply cleanup, preservation boundaries and DB health have offline coverage; no automatic periodic cleanup |
| CLI/package install | IMPLEMENTED for supported entry points | Wheel/editable and module CLI work; installed `.cmd` is the supported shortcut. The `.exe` generated from `console_scripts` is an environment/toolchain limitation |
| Version compatibility | PARTIAL | Capability-based result model and exec preflight gates added; app-server method negotiation is incomplete |
| AGENTS effective behavior | NOT_CONFIRMED | No matching per-run evidence in current audit |
| Skills effective behavior | NOT_CONFIRMED | Diagnostic listing is not proof of `exec` selection or use |
| MCP effective behavior/per-run restriction | NOT_SUPPORTED | No verified CLI per-run MCP allow/deny; child effectiveness remains unknown |
| TUI host tools in child process | NOT_CONFIRMED | Host namespace is distinct; Bridge does not depend on it |
| Business planning, Jira, pipeline lifecycle | OUT_OF_SCOPE | Belongs to consumers |
| Native Windows Service Control Manager integration | NOT_SUPPORTED | Use foreground process with documented external supervisor |
| Safe attach to arbitrary active Codex session | NOT_SUPPORTED | Watch is read-only; attach semantics are not offered |

`Codex support`, `Bridge support`, offline verification, real verification and
child-effective status are separate facts. This audit does not promote a host
session MCP/skill inventory to child or run-level availability.

The upstream [Python SDK client implementation](https://github.com/openai/codex/blob/main/sdk/python/src/openai_codex/client.py) is a useful reference, but the package is not installed as a runtime dependency here.

## MCP inventory and effective capability states

This is a development-session inventory, not a claim about the environment inherited by a Codex subprocess. See [`TOOLS_CATALOG.md`](TOOLS_CATALOG.md) for definitions, profile posture and per-MCP details.

| MCP namespace | Host `SESSION_VISIBLE` | CLI `CONFIGURED` / `ENABLED` | Host `CALLABLE` | Diagnostic child `CHILD_VISIBLE` / advertised | Auth status | `EFFECTIVE_FOR_RUN` |
|---|---|---|---|---|---|---|
| `codex_apps` | 73 host tools | Not in CLI list; app-server entry observed, enabled unknown | Schemas exposed, not called | Yes; 89 descriptors | Unknown | Unknown for `exec` |
| `codex_tui` | 9 host tools | Not in CLI list | Schemas exposed, not called | Not observed | Unknown | Unknown |
| `openaideveloperdocs` | 5 host tools | Yes / enabled | Confirmed by one harmless docs search | Yes; 5 descriptors, not invoked in child | `Unknown` in CLI | Unknown for `exec` |
| `pycharm` | 37 host tools | Yes / enabled | Host schemas exposed, not called | Config entry visible; handshake timeout, 0 descriptors | `Unsupported` in CLI | Unknown |
| `serena` | 23 host tools | Yes / enabled | Host schemas exposed, not called | Config entry visible; handshake timeout, 0 descriptors | `Unsupported` in CLI | Unknown |

The observed host total is 147 tools across these five namespaces. The app-server
child counts are a different surface and are not added to the host total. The host
catalog supplied 18 skills; diagnostic `skills/list` returned five enabled
`system` entries. Resource counts are unknown because generic resource enumeration
did not return. `codex login status` confirmed ChatGPT login; no credential values
were read or emitted.

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

## Resident service / daemon

| Capability | Codex support | Bridge support | Offline tested | Real tested | Notes |
|---|---|---|---|---|---|
| Foreground resident service | N/A | IMPLEMENTED | YES, fake subprocess | NO | Owns runtime manager and shared local scheduler until shutdown |
| Singleton per state DB | N/A | IMPLEMENTED | YES, duplicate fake start rejected | NO | OS advisory lock is authoritative; heartbeat/PID are diagnostic |
| Local service control IPC | N/A | IMPLEMENTED | YES, SQLite request/response | NO | Same-user local state directory trust model; no network listener |
| Health and service status CLI | N/A | IMPLEMENTED | YES, fake subprocess/API | NO | Sanitized SQLite snapshot; status does not prove model/API health |
| Metrics CLI | N/A | IMPLEMENTED | YES, fake subprocess/API | NO | Only counters actually available are reported; token usage may be null |
| TOML config and validation | N/A | IMPLEMENTED | YES, precedence/type/path fixtures | NO | CLI > supported env > file > defaults for supported settings |
| Graceful stop/restart request | N/A | IMPLEMENTED | YES, fake service stop | NO | WAIT/INTERRUPT/FORCE; process restart launches a new local process |
| Startup recovery | N/A | PARTIAL | YES, existing fake recovery | NO | Conservative; uncertain claimed runs are not replayed |
| Cross-process turn submission | N/A | IMPLEMENTED for typed commands | YES, fake daemon | NO inference | `SUBMIT_EXEC_RUN`, `CREATE_THREAD`, and `START_TURN` use the shared SQLite command queue |
| Windows SCM service integration | N/A | OUT_OF_SCOPE | NO | NO | Foreground ready; external supervisor guidance only |
| Automatic periodic data retention | N/A | PLANNED | NO | NO | Explicit `maintenance clean` performs retention; the service does not schedule it periodically |
# Cross-process daemon submissions

| Capability | Codex support | Bridge support | Offline tested | Real tested |
|---|---|---|---|---|
| Service command queue / typed submit | N/A (bridge control plane) | IMPLEMENTED: `SUBMIT_EXEC_RUN`, `CREATE_THREAD`, `START_TURN` | Yes, including idempotency, claim recovery and fake-daemon CLI flow | No Codex inference; fake daemon only |
| Windows module entry point | N/A | IMPLEMENTED | `python -m p4_codex_bridge --version` passes | VERIFIED |
| Windows CMD launcher | N/A | IMPLEMENTED | Wrapper uses the adjacent environment Python; wheel installs it under `Scripts`; package/module validation passes | VERIFIED |
| Windows console-script EXE | N/A | ENVIRONMENT_LIMITATION | P4 and independent tiny launcher `.exe` hang while their Python invocation works; no lower-level cause established | Not required; do not execute in doctor |

## 2026-10-07 final release gate

| Capability | Codex support | Bridge support | Offline tested | Real tested | Evidence / limit |
|---|---|---|---|---|---|
| Installed-wheel foreground daemon | Codex 0.160.1 app-server | IMPLEMENTED for tested lifecycle | YES | YES, one turn | Fresh wheel venv; cross-process `CREATE_THREAD`/`START_TURN`, read-only watch, exact `OK`, graceful stop. Effective model and usage are not exposed. |
| Service cleanup after completed turn | N/A (bridge-local) | IMPLEMENTED for tested path | YES | YES | STOPPED, 0 active runs, queue, locks, approvals and pending payloads. |
| App-server required RPCs in daemon | Local generated schema plus runtime handshake | SUPPORTED_WITH_LIMITATIONS | YES | YES for create/start path | Schema source `GENERATED_LOCAL_SCHEMA`; runtime smoke passed one create/start path. Not a guarantee for optional protocol methods. |
| Luna model selection | Model catalog listed `gpt-6-luna` | Explicit request supported | N/A | Requested; effective model NOT_CONFIRMED | Catalog listed seven models; one requested turn completed, but app-server did not report effective model identity. |
