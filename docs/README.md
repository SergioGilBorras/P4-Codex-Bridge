# P4-Codex-Bridge documentation

This index describes the **current 1.1.0 source tree**. Product functionality, verified local CLI capability, and intended roadmap work are distinct. The Codex CLI installation, authentication, protocol availability, and effective MCP/skills permissions can vary by environment.

## Start here

- [Installation](INSTALLATION.md) — install, CLI preflight and Windows invocation.
- [Python API](PYTHON_API.md) — public `CodexBridge` methods, signatures and usage.
- [Execution contract](CONTRACT.md) — run arguments, results and error handling.
- [CLI](CLI.md) — operator commands and JSON/JSONL behavior.
- [Architecture](ARCHITECTURE.md) — components and state ownership.
- [Feature catalog](FEATURE_CATALOG.md) — implemented, partial and unavailable features.
- [Capability matrix](CAPABILITY_MATRIX.md) — which surfaces expose which features, and what can actually be verified.
- [Security](SECURITY.md) — filesystem, approvals, external MCP and identity limits.
- [Known limitations](KNOWN_LIMITATIONS.md) — operational caveats.
- [Roadmap](ROADMAP.md) — proposals only, not implemented promises.

## Operations

- [Configuration](CONFIGURATION.md), [profiles](PROFILES.md) and [version compatibility](VERSION_COMPATIBILITY.md).
- [Service](SERVICE.md), [Windows service guidance](WINDOWS_SERVICE.md), [concurrency](CONCURRENCY.md) and [resource scheduler](RESOURCE_SCHEDULER.md).
- [Lifecycle](LIFECYCLE.md), [recovery](RECOVERY.md), [SQLite recovery](DB_RECOVERY_MATRIX.md), [observability](OBSERVABILITY.md) and [run discovery](LIVE_OBSERVABILITY.md).
- [Events](EVENTS.md), [approvals](APPROVALS.md), [MCP](MCP.md), [skills](SKILLS.md) and [AGENTS behavior](AGENTS_BEHAVIOR.md).

## Development and testing

- [Development workflow](DEVELOPMENT_WORKFLOW.md), [test catalog](TEST_CATALOG.md), [model-use policy](TEST_TOKEN_BUDGET.md).
- [Tools](TOOLS_CATALOG.md) and [skills catalog](SKILLS_CATALOG.md) explain *runtime discovery*; they do not assert that a previous development-session inventory is installed now.

The active documentation intentionally focuses on supported behavior and limitations. Versioned release/checklist or architecture-decision records elsewhere in the repository are not the source for present capabilities.
