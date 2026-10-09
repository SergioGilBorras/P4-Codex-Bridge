# Security boundary for Codex capabilities

## Current guarantees and limits

| Area | Classification | Guarantee / limitation |
|---|---|---|
| Filesystem sandbox | BEST_EFFORT | Bridge maps verified Codex sandbox modes; it does not claim an OS-level sandbox beyond Codex's actual implementation. |
| MCP isolation | NOT_GUARANTEED | Codex exposes no verified per-run MCP filter or empty-MCP receipt. Requested isolation is rejected. |
| External MCP side effects | BEST_EFFORT | Unknown effective MCP set rejects by default. Trusted, acknowledged opt-in permits unfiltered risk with a warning; no tool-level classification/filter is claimed. |
| Project config | BEST_EFFORT | Default policy rejects discovered project config unless explicitly permitted for a trusted project. Codex trust and child effective config are not inferred from cwd alone. |
| AGENTS / skills | NOT_GUARANTEED | Visibility and use are not claimed without a run-level receipt. Default project context is restricted; trusted opt-in does not imply MCP isolation. |
| Approvals | GUARANTEED by bridge policy | Manual resolution is default; timeout rejects; no automatic approval default. Codex's own approval semantics still apply. |
| Process ownership | BEST_EFFORT | Bridge records process identity and only controls matching registered processes; OS identity checks are not a multi-user security boundary. |
| Local IPC | BEST_EFFORT | SQLite command/control channel is local state-directory access. Filesystem ACLs are inherited and not hardened by the bridge. |
| Multi-user isolation | NOT_GUARANTEED | State directory, journal and local control are intended for a single OS user/trust boundary. Do not share across mutually untrusted users. |

The current per-run MCP isolation limitation remains security-significant. All supported submission paths must enforce the typed security gate; a new path without that gate is a security regression.

## Runtime-dependent limits

- No verified per-run MCP/tool allowlist or empty-MCP receipt is exposed by the supported Codex interface.
- A read-only filesystem sandbox does not prove that external MCP tools are read-only.
- A diagnostic app-server's tool/skills inventory does not establish access for a separate exec run.
- Capability status must be scoped to the process and run being observed.

## Required posture

`RunSecurityPolicy` makes project trust (`TRUSTED`, `UNTRUSTED`, `UNKNOWN`),
project context, external MCP use, side-effect MCP use, isolation requirements
and explicit risk acknowledgement one typed policy. The bridge validates it
before direct/managed exec, app-server thread/turn work, and again when the
service processes typed cross-process commands. It records only the
sanitized policy decision metadata. Unknown effective MCP state is not treated
as no MCPs. Since there is no run-specific proof that the child MCP set is
empty, default execution rejects until the caller opts into the unfiltered MCP
risk under a trusted project with explicit acknowledgement.

1. Keep MCP capability state scoped to the exact process and run. Never promote `SESSION_VISIBLE`, `CONFIGURED`, `ENABLED`, or `ADVERTISED` to `CALLABLE` or `EFFECTIVE_FOR_RUN` without matching evidence.
2. `analysis` remains read-only at the filesystem sandbox, but do not claim that this alone prohibits external MCP side effects.
3. `planning` may use read-oriented connectors only after their actual tool surface is identified and write tools can be denied.
4. `implementation` requires explicit workspace-write permissions; external integration side effects still require a separate explicit policy.
5. `validation` should receive only tools required by its verifier.
6. Because Codex has no verified per-run MCP filter, `require_mcp_isolation`
   rejects before launch. A TRUSTED project and explicit risk acknowledgement
   can opt into inherited external MCP risk, with a warning; the bridge still
   cannot deny individual external tools. This is a current limitation, not an
   isolation guarantee.
7. Never invoke external write/delete/deploy/plugin actions as a capability-discovery probe.

## Secret handling

Do not return bearer tokens, cookies, auth headers, Codex auth internals, or environment values from discovery. Preserve only sanitized auth status labels. MCP config URLs and tool names may be reported when non-sensitive, but never include secret-bearing URL query parameters or credentials.

See [MCP discovery](MCP.md), [skills](SKILLS.md), [AGENTS behavior](AGENTS_BEHAVIOR.md), and the [capability matrix](CAPABILITY_MATRIX.md).

## Git repository context option

The current Python API offers `skip_git_repo_check=True` for direct and managed
`codex exec` only. It omits Codex's Git-context/repository check; it does not
disable Codex's sandbox or relax bridge `cwd`/`allowed_roots` validation,
permissions, approval policy, or MCP security policy. It defaults to false and
is capability-gated against the installed `codex exec --help`. A CLI that does
not advertise the flag is rejected before work starts. Callers should enable it
only for a specific existing workspace that is intentionally not a Git
repository.

## Resident service boundary

- The control channel is a local SQLite database under `state_dir`; it binds no
  network socket. Anyone with filesystem access to that directory can inspect
  or submit local control rows. This is not multi-user authorization. Use a
  per-user local directory with appropriate inherited Windows ACLs; the Bridge
  does not change ACLs.
- The lock file contains PID/instance metadata, while the OS advisory lock is
  the singleton authority. Process identity mismatch is never treated as
  ownership.
- Logs rotate by size/count and omit prompts by default. State, logs and config
  paths still require operator access control and retention.
- Service control stops/restarts its owned manager; it never kills arbitrary
  processes. Windows wrappers and service-process crash recovery remain
  external.
- Service config cannot filter inherited MCPs. A read-only sandbox does not
  prevent an external MCP from producing side effects.

## Guarantee level

| Control | Classification | Limit |
|---|---|---|
| subprocess argument arrays, `shell=False`, prompt on stdin | GUARANTEED by Bridge code path | Does not constrain behavior inside Codex or MCP servers |
| bridge-created run ID and registry ownership before termination | GUARANTEED for managed runs | A crash before durable identity/child metadata is reconciled conservatively |
| result/event/metadata secret redaction | BEST_EFFORT | Pattern redaction is not a general secret detector; do not submit credentials |
| Windows process identity check before acting on a registered PID | BEST_EFFORT | OS query failure prevents safe termination; PID alone is never sufficient |
| private state directory ACL | NOT_GUARANTEED | Bridge does not edit Windows ACLs; choose a per-user protected directory |
| external MCP deny-by-default per run | NOT_GUARANTEED | Installed Codex interface has no verified per-run MCP allow/deny filter |
| read-only sandbox prevents external MCP writes | NOT_GUARANTEED | Filesystem sandbox and MCP authorization are distinct |
| same-user SQLite control channel authorization | NOT_GUARANTEED across local users | Anyone who can write the state directory can manipulate its records |
| project `AGENTS.md`/skills/config visibility for a specific run | NOT_CONFIRMED | Host/diagnostic visibility is not a run-level receipt |

The Bridge must not present `analysis` as safe from external side effects when
unfiltered inherited MCPs are enabled. Do not launch sensitive work in
untrusted projects/configurations without explicit operator acknowledgement.
# Resident submission boundary

The command channel is same-machine SQLite IPC. Typed request models reject
unknown API fields, cap prompt/metadata/payload size, validate paths and
permissions, and the daemon repeats validation before dispatch. Exec cwd and
thread cwd must be under configured `codex.allowed_roots`; the default is the
service workspace. No unauthenticated remote endpoint is opened. Local users
who can read/write the state directory can submit/control work, so multi-user
isolation is not guaranteed; keep the directory private using normal Windows
account ACLs. A claimed command is never re-executed after an ambiguous crash.
