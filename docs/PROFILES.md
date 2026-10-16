# Execution profiles and permissions

Profiles are platform execution defaults, not P4 business logic. The only supported named exec profile is `analysis`; other profile names are rejected.

| Profile | State | Current behavior |
|---|---|---|
| `analysis` | **IMPLEMENTED** for `codex exec` | `read-only`, approval `never`, isolated user-config flag, explicit cwd. This does not prove that project instructions/MCP behavior is isolated. |

`CodexBridge.start_turn()` app-server turns accept explicit `CodexPermissions`; they do not implicitly apply a named profile. The installed turn schema supports sandbox values `read-only`, `workspace-write`, and `danger-full-access`, and approval policies `never`, `on-request`, and `untrusted`. For app-server `workspace-write`, the bridge sets `writableRoots` to the validated cwd and `networkAccess` to false. This is the verified turn request mapping and does not override unknown native policy layers.

Approval handling is separately configurable: `MANUAL` is default; `AUTO_REJECT` and `NEVER_EXPECT_APPROVAL` explicitly decline. `AUTO_APPROVE_SAFE_ONLY` is unsupported because the bridge has no deterministic safe-action classifier. Full access requires caller-supplied `on-request` and is never paired with automatic approval by a default profile.

`config_policy` applies to the CLI `exec` API:

- `isolated`: adds `--ignore-user-config`; it does not establish that project config, AGENTS, skills or MCPs are suppressed.
- `project`: uses Codex native layered settings for the chosen cwd.
- `explicit`: layered settings plus validated `-c` overrides.
- `user`: rejected because the installed CLI cannot select only user config.

## Execution controls

`CodexPermissions` optionally accepts `writable_roots` and `network_access`. Exec adds validated writable roots using `--add-dir`; workspace-write network access is sent as the schema-backed `sandbox_workspace_write.network_access` config setting and defaults to false. These do not filter MCP/network tools. `danger-full-access` has no independent network setting in the observed exec contract, requires explicit `on-request`, and remains non-default.

`resume()` and `fork()` restore stored session policy. The API refuses unless the caller sets `confirm_inherited_permissions=True`; CLI flags cannot replace that policy. `review()` accepts exactly one of `uncommitted=True`, `base=...`, or `commit=...`, matching local help. There is no arbitrary file-list review option.

Reasoning summary (`auto`, `concise`, `detailed`, `none`) and verbosity (`low`, `medium`, `high`) use the installed config schema. Reasoning effort remains model-specific; use the dynamic `supportedReasoningEfforts` list. Structured output and final-message capture use the CLI options; all their temp files are bridge-owned and removed after success/failure/timeout.

The diagnostic config/MCP/skills methods launch a separate app-server child at the requested cwd. They do not prove the same resources are loaded by `exec`. For development-session MCPs, child visibility remains `unknown` until run-specific evidence exists. No P4 profile implicitly allows destructive external integrations.

### MCP policy status

The installed `exec` interface does not expose a verified per-run MCP/tool allowlist, and project configuration may still apply under `isolated`. This limitation prevents a bridge guarantee that inherited external tools have no side effects. Do not use this bridge with untrusted project MCP configuration unless the risk is explicitly assessed and acknowledged under the security policy. Codex Apps and TUI tools visible in the development host are not assumed to be child-visible. See the [roadmap](ROADMAP.md) for proposed enforceable profiles and tool controls.

See [Python API](PYTHON_API.md), [architecture](ARCHITECTURE.md), and [approval behavior](APPROVALS.md).
