# Capability matrix

Capabilities have three distinct layers: **bridge implementation**, **installed Codex CLI/protocol advertisement**, and **effective access in a particular run**. A local feature probe does not prove model entitlement, permissions, external MCP availability, or the exact child configuration.

| Feature | Bridge implementation | Runtime evidence required |
|---|---|---|
| One-shot `codex exec` | Implemented | Installed executable, login, exec command and a successful matching run |
| Managed queued exec | Implemented | As above; pending dispatch depends on local scheduler resources |
| `skip_git_repo_check` for `run/start` | Implemented, opt-in, default false | `--skip-git-repo-check` in installed `codex exec --help`; bridge rejects unsupported requested flag |
| Structured output | Implemented for exec | `--output-schema` in CLI help; emitted JSON syntax validated; schema completeness not guaranteed by bridge parser |
| Capture final message | Implemented for exec | `--output-last-message` in CLI help and a final-message file from that run |
| Exec resume/fork/review | Implemented with typed limits | Support for operation-specific installed CLI subcommand; session permissions/targets must be respected |
| Models | Dynamic discovery implemented | Installed `model/list` and account access for the requested model; discovery is not entitlement |
| Sandbox / approvals | Typed mapping and security gate implemented | Native sandbox semantics and permission approvals remain dependent on Codex |
| App-server runtime | Experimental manager, threads, turns, streams and approvals | Generated local schema, successful initialize handshake and successful matching RPC |
| Scheduler | Implemented for managed exec and app-server | Local SQLite health, ownership/locks and resource limits |
| Local service client | Implemented | Foreground service running with compatible schema, state directory and same-user access |
| MCP/skills diagnostics | Implemented as separate diagnostic app-server calls | May show configured/advertised resources; does not confirm exec-child callability or effective run use |
| Per-run MCP tool allow/deny | Not supported as an enforceable bridge guarantee | Requires an upstream-supported isolation mechanism and matching-run proof |
| Active turn adoption / full replay | Not supported as an automatic guarantee | Conservative local recovery only; no unsafe replay |
| Windows SCM wrapper | Not bundled | External supervisor/operator configuration |

## Runtime capability classification

- `SUPPORTED` or a positive CLI help probe: a command/flag is advertised by the installed version.
- `SUPPORTED_WITH_LIMITATIONS`: generated app-server schema suggests a method but no matching successful RPC is yet confirmed.
- `UNKNOWN`: missing or insufficient evidence; do not interpret as available.
- `NOT_SUPPORTED`: an authoritative negative observation or a feature absent from the bridge contract.
- `EFFECTIVE_FOR_RUN`: requires evidence tied to that particular bridge run ID, not a host-session tool list or separate diagnostic child.

For programmatic inspection, use `CodexBridge.get_capabilities()` and documented app-server diagnostic APIs, then verify required features before submission. The 1.1 `get_capabilities()["exec"]["skip_git_repo_check"]` entry reports a boolean detected from CLI help; `skip_git_repo_check_capability` adds provenance/status.

Do not infer capabilities from a Codex CLI version number alone. If the CLI, account, project trust or app-server schema changes, inspect again. See [version compatibility](VERSION_COMPATIBILITY.md), [security](SECURITY.md) and [roadmap](ROADMAP.md).
