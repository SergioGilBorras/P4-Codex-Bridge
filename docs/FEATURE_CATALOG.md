# Current feature catalog

This page describes the current P4-Codex-Bridge 1.1.0 source tree. **Implemented** means a bridge code path exists with offline tests, not that a particular Codex CLI installation or account supports it. **Partial** means supported with explicit limits. **Unavailable** means no general supported bridge interface.

| Area | Status | Current behavior / limit |
|---|---|---|
| Python `CodexBridge.run()` | Implemented | Synchronous exec with stdin prompt, typed cwd/model/permissions/timeout, JSONL parsing and normalized `RunResult` |
| Managed `CodexBridge.start()` | Implemented | Queued exec, shared SQLite scheduling/locks, cancellation, status and one-time result retrieval |
| `skip_git_repo_check` | Implemented, opt-in | Keyword-only bool on Python `run()`/`start()`, default `False`; requires advertised CLI flag |
| Exec `resume()`, `fork()`, `review()` | Implemented with limits | Separate APIs; session policy acknowledgement for resume/fork, one supported review target per request |
| Structured output / last message | Implemented | CLI-backed temp files; syntax/response verification, not a guarantee that arbitrary schemas are fully satisfied |
| Discovery | Implemented with limits | CLI version/help, model catalog, generated app-server schema and config/MCP/skills diagnostic child |
| Resource scheduler | Implemented with recovery limits | Global/backend/profile limits, workspace locks, queue state; direct `run()` not scheduled |
| Resident app-server manager | Partial | Experimental runtime support for threads/turns, events, explicit approvals and terminal-state reconciliation |
| Local foreground service | Implemented with limits | Same-user process/SQLite command boundary and typed Python service-client requests |
| Process and state observability | Partial | Registry IDs, status, inspect, watch, health and metrics; no attachment or reliable full message-delta replay |
| Security controls | Partial / enforced defaults | `allowed_roots`, sandbox/approval validation, `RunSecurityPolicy`, bounded captures and redaction; external MCP isolation is not guaranteed |
| Per-run MCP allow/deny filtering | Unavailable | No verified Codex-protocol enforcement surface |
| Automatic approval of supposedly safe actions | Unavailable | No deterministic safe-action classifier |
| Active turn/process adoption after uncertain controller loss | Unavailable | Conservative status reconciliation; no blind replay |
| Windows native SCM service wrapper | Unavailable | Foreground service supported; service-manager integration is operational guidance, not a bundled SCM implementation |
| Independent Node/JavaScript bridge API | Unavailable | Python package and operator CLI are the supported bridge surfaces |

## Usage guarantees

- Python method availability is not proof of runtime CLI flag support. Probe `get_capabilities()` and validate preflight.
- Models returned by discovery are not proof of subscription entitlement.
- MCP and skills visible to a host or a diagnostic child are not automatically effective for a run.
- Real-model smoke scripts require explicit opt-in; offline unit/fake integration tests do not send model calls.

For precise signatures see [Python API](PYTHON_API.md), for enforced boundaries see [security](SECURITY.md), and for proposals see [roadmap](ROADMAP.md).
