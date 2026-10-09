# Roadmap

This roadmap lists **possible next work**, not functionality that currently exists. Items have no committed delivery date, version, security guarantee, or execution authorization. Implementation requires separate design, tests and review.

## Priority candidates

| Area | Present constraint | Candidate improvement | Acceptance evidence |
|---|---|---|---|
| Per-run MCP/tool controls | Current Codex CLI/app-server interface offers no bridge-verified allow/deny filter for inherited external MCP tools. `READ_ONLY` filesystem permissions do not control external tool side effects. | Evaluate upstream-supported per-run isolation or enforceable MCP policy; never simulate isolation using names or a diagnostic inventory. | Actual matching-run permission receipt, negative tests for external writes and explicit fail-closed behavior. |
| Runtime recovery | Local metadata and terminal-state reconciliation work, but uncertain active turns and claimed exec jobs are not automatically adopted or replayed. | Investigate safe reconciliation and ownership recovery without replaying ambiguous side-effecting work. | Process-identity checks, crash tests, no duplicate execution. |
| Protocol coverage | App-server protocol is experimental and support depends on generated schema plus runtime handshake. Tool-user-input and MCP elicitation are not generally handled. | Add strictly validated request handlers where the installed protocol supports them. | End-to-end fake protocol tests, manual opt-in proof, safe default rejection. |
| Child configuration evidence | Diagnostic app-server can describe config, MCP and skills, but this does not establish visibility for a separate exec run. | Build run-specific observability/receipts without executing unsafe tools. | Evidence tied to a bridge run ID; clear unknown/not-supported states. |
| Windows operation | A foreground service and module/CMD launch work; an SCM service wrapper and reliable generated `.exe` behavior are not guaranteed. | Improve packaging diagnostics and investigate supported service wrapper design. | Repeatable Windows CI, service lifecycle and launcher tests. |
| Documentation / CI | Offline unit and fake integration tests exist; public repository CI must be checked independently. | Add automated doc-link validation, Python version/platform tests and installation smoke checks without model calls. | Repeatable checks on pull requests, no real inference by default. |

## Additional possibilities

- Additional named profiles (planning, implementation, validation, documentation) **only** after defining explicit, enforceable policies. `analysis` is the supported default profile today.
- Optional support for `skip_git_repo_check` in additional submission surfaces if their typed contracts and security gates can be extended safely; currently available only in Python `CodexBridge.run()` and `start()`.
- Consumer integration guides and examples for external applications, without claiming installations or deployments that have not been verified.

## Design principles

1. Preserve typed interfaces and strict opt-in for capabilities that relax checks.
2. Prefer observed CLI/protocol features over version assumptions.
3. Keep project-level business scheduling outside the bridge.
4. Make uncertain or unsupported behavior explicit.
5. Keep automated tests offline; real model tests remain separately authorized.
