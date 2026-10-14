# Skills discovery and child behavior

P4-Codex-Bridge does **not** ship a fixed inventory of Codex skills. Installed global and project skills, their instructions and visibility depend on the current Codex CLI, configuration, environment and run. Skills visible in a development host are **not** automatically available inside an `exec` subprocess.

## Supported diagnostics

- `CodexBridge.list_effective_skills()` queries `skills/list` in a **separate diagnostic app-server** where its installed protocol supports that method.
- `get_effective_capabilities(include_diagnostics=True)` may include that scoped skills diagnostic.
- A diagnostic descriptor proves only that a particular diagnostic process advertised the skill. It is not proof that `codex exec` loaded or used it, and cannot be promoted to `EFFECTIVE_FOR_RUN` without run-matched evidence.
- Skill metadata, instructions, script availability and permissions must be inspected independently for the exact environment; do not guess an enabled skill from a local file name.
- MCP tool inventories are not skill inventories. Missing observations are `UNKNOWN`, not evidence that no skills exist.

## Consumer guidance

When a consumer genuinely needs a skill, inspect its installed instructions and limitations, verify permitted operations, and require a receipt from the matching run before claiming that it was invoked. Never run external write/delete/network probes merely to test skill availability. A skill does not grant permissions or bypass the approval/security policy.

See [capability verification](CAPABILITY_MATRIX.md), [MCP](MCP.md), [security](SECURITY.md) and [Python API](PYTHON_API.md).
