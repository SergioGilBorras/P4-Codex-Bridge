# Tools and MCP discovery

This is a guide to **current bridge operations**, not an inventory of development-session tools. Third-party MCP namespaces, connected apps, IDE integrations, host tools and their permissions vary by user, session, runtime and environment; this repository does not guarantee that any particular provider or count is installed.

## Which surface to inspect

| Need | Reliable source | What it cannot establish |
|---|---|---|
| Installed CLI flags and model controls | `CodexBridge.get_capabilities()`, local `codex --help` / `codex exec --help` | Account entitlement or later run permissions |
| Available models | Bridge model discovery via installed `model/list` | Permission to use every model |
| Configured MCP server descriptors | `list_configured_mcps()` in a short-lived app-server diagnostic | Exec-child visibility, callability or side-effect safety |
| Skills advertised to a diagnostic app-server | `list_effective_skills()` | Skills that a separate run actually loads |
| Local runtime state | `p4-codex ps` / `inspect` / `watch` / `resources` | Attach or complete replay of model-output deltas |
| Host-session IDE or connected-app tools | The *active host* tool/skill discovery mechanism | Propagation of host handles into a Codex CLI child |

## Safe operational rules

1. Use the narrowest trustworthy source of evidence for the task.
2. Treat host, diagnostic-child and actual-run capabilities as separate.
3. Do not assume any MCP or tool is callable merely because its schema is listed.
4. Do not invoke external write, delete, deploy, credential or plugin actions as discovery probes.
5. Never infer that `READ_ONLY` filesystem sandbox prevents external MCP side effects.
6. For child effectiveness, require evidence tied to the exact run, or report `UNKNOWN`.

See [MCP](MCP.md), [skills catalog](SKILLS_CATALOG.md), [capabilities](CAPABILITY_MATRIX.md), [security](SECURITY.md) and [roadmap](ROADMAP.md).
