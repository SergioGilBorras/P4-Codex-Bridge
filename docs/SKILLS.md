# Skills discovery and child behavior

## Current guarantees and limits

Codex may discover global or project skills according to its installed configuration. Skill metadata, instructions and supporting files are loaded according to Codex's own skill-discovery rules; see [Codex customization documentation](https://developers.openai.com/codex/skills).

P4-Codex-Bridge can request a diagnostic app-server `skills/list` response through `list_effective_skills()`. That response describes resources visible to **the diagnostic child**, not a guaranteed skill inventory or proof of invocation by a separate `codex exec` run. Host-session skills, project files and configured MCP resources must not be inferred to be available to the execution child.

| Capability | Current status | Evidence needed |
|---|---|---|
| Host skill inventory | Environment-dependent | Inspect the active development host; never use a stored count as an installation guarantee. |
| Project skill files | Workspace-dependent | Inspect the chosen workspace and Codex configuration at runtime. |
| Diagnostic app-server skill list | Diagnostic only | Check the current `skills/list` response and its advertised scopes. |
| Skill invocation in a bridge exec run | Not guaranteed | Evidence tied to the exact execution, not a separate app-server or host session. |
| MCP-provided skill resources | Not guaranteed | Inspect resources separately; MCP tools and Codex skills are not interchangeable. |

The bridge has no verified per-run skill allowlist or suppression receipt. Project trust, configuration selection and external MCP risk require independent security assessment. Real skill invocations are opt-in operations that may consume model usage. See [capability matrix](CAPABILITY_MATRIX.md), [MCP](MCP.md) and [security](SECURITY.md).
