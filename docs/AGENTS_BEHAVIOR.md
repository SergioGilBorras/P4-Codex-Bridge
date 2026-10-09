# AGENTS.md behavior

Codex may use project instructions from its configured context. The bridge does not promise that an `AGENTS.md` file is loaded or suppressed for a particular `codex exec` run merely because a project or diagnostic app-server exposes it.

## Current controls

- `cwd` is a required existing directory and can be constrained through `allowed_roots`.
- `config_policy="isolated"` requests the installed CLI's user-config isolation option, but it does not by itself establish complete project-context, skill or MCP isolation.
- `RunSecurityPolicy` governs project trust and explicit acknowledgement of unfiltered external MCP risk.
- The bridge has no verified per-run AGENTS file allowlist or definitive effective-for-run receipt.

## Verification

The manual `tests_real/smoke_agents_context.py` fixture can be inspected to understand the expected check. It is not part of the automatic suite and may make a real Codex call. Do not execute it without explicit authorization and an assessment of external MCP risks.

A host-session or diagnostic-child observation is not proof that a given exec run loaded instructions. Mark the result `UNKNOWN` unless it is tied to that run.

See [profiles](PROFILES.md), [MCP](MCP.md), [security](SECURITY.md), and [roadmap](ROADMAP.md).
