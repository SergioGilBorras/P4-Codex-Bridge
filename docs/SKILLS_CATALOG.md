# Skills discovery and use

Skills are **environment- and session-specific**. P4-Codex-Bridge does not ship or promise a fixed host skills catalog. Tool handles and skills visible in a development host are not automatically inherited by a Codex subprocess.

## Available bridge behavior

- `CodexBridge.list_effective_skills()` queries `skills/list` in a separate diagnostic app-server where supported.
- `get_effective_capabilities(include_diagnostics=True)` can add a scoped skills diagnostic.
- A diagnostic skills descriptor means advertised/configured in that child, **not** necessarily loaded or used by `codex exec`.
- Do not treat skill enablement as proof of availability to a particular `bridge_run_id`.

## Consumer guidance

For skill-dependent behavior, discover the skill in the exact environment, inspect its instructions and limitations, and avoid triggering external actions without authorization. If no matching-run evidence is available, record effectiveness as `UNKNOWN` rather than asserting a fixed inventory.

See [skills](SKILLS.md), [MCP](MCP.md), [capabilities](CAPABILITY_MATRIX.md) and [security](SECURITY.md).
