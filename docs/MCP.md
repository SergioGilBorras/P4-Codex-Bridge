# MCP configuration and child visibility

P4-Codex-Bridge can inspect **configured and advertised** MCP tools through a short-lived diagnostic app-server. This does not make those tools available to a separate `codex exec` run and does not establish a per-run permission boundary.

## Evidence scopes

| Scope/status | Meaning |
|---|---|
| `SESSION_VISIBLE` | A host agent interface exposes a tool name/schema |
| `CONFIGURED` | A configuration source lists an MCP server |
| `ENABLED` | A source explicitly reports the server enabled |
| `ADVERTISED` | A diagnostic child reports server/tool descriptors |
| `CALLABLE` | A harmless invocation through that exact child actually succeeds |
| `CHILD_VISIBLE` | A named child process reports the capability |
| `EFFECTIVE_FOR_RUN` | Evidence is bound to the matching `bridge_run_id` |

Never promote a configured server, advertised tool or host-session schema to `EFFECTIVE_FOR_RUN` without matching evidence. A missing inventory is `UNKNOWN`, not proof that no MCP tools exist.

## Implemented diagnostics

- `list_configured_mcps()` can ask a separate diagnostic app-server for `mcpServerStatus/list`. It reports descriptors without invoking tools.
- `list_effective_skills()` is a distinct skills diagnostic.
- `get_effective_capabilities(include_diagnostics=True)` combines safe observations and preserves unknown exec-child effectiveness.

These methods do **not** grant or revoke tools in another Codex child. Depending on `config_policy` and the installed app-server protocol, a diagnostic call may be unavailable; for instance, app-server diagnostics cannot claim isolated effective configuration where native support is absent.

## Security controls

`RunSecurityPolicy` gates project trust, project context, requested MCP isolation, external MCP allowance, side-effect risk and explicit acknowledgement on supported run/submission routes. The bridge cannot guarantee a verified per-run MCP tool allow/deny filter. Requested strict isolation fails closed; a trusted, explicit acknowledgement of unfiltered external-MCP risk can permit execution with a warning, **not** with an isolation guarantee.

`READ_ONLY` applies to native filesystem sandbox policy; a side-effecting external MCP may write to unrelated services. Diagnostic discovery must not call destructive tools merely to prove access.

See [security](SECURITY.md), [capabilities](CAPABILITY_MATRIX.md), and [roadmap](ROADMAP.md).
