# MCP configuration and child visibility

## Evidence snapshot: 2026-10-06

The host session exposed these MCP namespaces: `codex_apps` 73 tools, `codex_tui` 9, `openaideveloperdocs` 5, `pycharm` 37, and `serena` 23. These are `SESSION_VISIBLE` counts for this turn, not a stable inventory. Host auth is unknown except where the Codex CLI reports a status.

`codex mcp list` showed three global CLI entries, all enabled:

| Name | CLI auth status | Diagnostic child evidence |
|---|---|---|
| `serena` | Unsupported | Config entry was visible to the diagnostic app-server, but startup timed out during MCP handshake; 0 tools announced. |
| `pycharm` | Unsupported | Config entry was visible to the diagnostic app-server, but startup timed out during MCP handshake; 0 tools announced. |
| `openaideveloperdocs` | Unknown | Five tools announced by the diagnostic app-server. One harmless host-session search succeeded; no child tool was invoked. |

The app-server diagnostic also listed `codex_apps` with 89 tools. Its entry was not present in `codex mcp list`; its source and enabled state for a CLI execution are unknown. No `codex_tui` entry appeared in either the CLI MCP list or the diagnostic app-server. Do not infer that TUI tools transfer to a child.

The host snapshot exposed tool schemas for these namespaces; only the OpenAI Docs search was actually called in this phase. The diagnostic child advertised names/schema, which is `ADVERTISED`, not proof of `CALLABLE`. No Jira, deployment, document, plugin, deletion, or other write operation was invoked.

MCP resource enumeration did not return within the tool-call wait window, so resource counts are unknown. The 18 skills supplied to the host are a separate session inventory, not per-MCP resource counts.

## State model

Keep these states separate and attach their source/scope:

| State | Evidence needed |
|---|---|
| `SESSION_VISIBLE` | Tool namespace/schema is exposed to the current host agent. |
| `CONFIGURED` | A config/list endpoint shows the server entry and its scope. |
| `ENABLED` | The source explicitly reports enabled; do not infer from registration. |
| `ADVERTISED` | A child MCP status response returned tool descriptors. |
| `CALLABLE` | An invocation through that exact child succeeded. Do not test destructive tools to establish it. |
| `CHILD_VISIBLE` | The named child process reported the server/tool. Name the child kind (`diagnostic_app_server`, `exec`, etc.). |
| `EFFECTIVE_FOR_RUN` | Evidence tied to the exact `bridge_run_id` shows the run could use or used the capability. |

The Bridge exposes `list_configured_mcps()` through `mcpServerStatus/list` in a short-lived diagnostic app-server. It reports advertised tools, but does not invoke them. `get_effective_capabilities()` leaves run-level visibility/effectiveness unknown. These results do not stand in for the separate `codex exec` child.

## Control and security

Installed `codex --help` supports `--ignore-user-config`, `-c/--config`, and profiles; the observed `codex exec` interface does not expose an MCP/tool allowlist. The app-server status/config APIs inspect servers but do not provide the Bridge a verified per-turn denylist. Therefore `analysis` cannot claim that all external MCP side effects are blocked merely because its OS sandbox is read-only. The current account's diagnostic app-server announced external write/deploy/destructive tools.

The current `RunSecurityPolicy` gate is implemented for direct exec, managed
exec, app-server runs and daemon submissions. It rejects requested MCP
isolation, unknown effective MCP state, untrusted use of project context, and
external MCP use without trusted-project plus explicit risk acknowledgement.
The bridge cannot produce a run-specific `NONE_CONFIRMED` receipt today, so a
default run fails closed while MCP effectiveness is unknown. An explicitly
acknowledged external-MCP opt-in returns a warning. This gate cannot filter
Codex's MCP tools and does not guarantee isolation.

The OpenAI Developer Docs MCP is for development verification only, never a runtime dependency of P4-Codex-Bridge.
