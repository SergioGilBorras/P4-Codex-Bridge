# P4-Codex-Bridge instructions

## Project boundary

This repository is shared infrastructure for invoking Codex from P4. Planned consumers are P4-Planning-Agent, P4-Jira-Agent-Orchestrator and GestorProyectosIA. Do not modify consumers or duplicate the Codex client there unless an integration task explicitly requests it. Do not add Jira, scheduling, planning, requirements, pipeline or Orchestrator lifecycle logic here.

## Tooling and discovery

- Before complex work, inspect live tools/MCP and skills. **Tool discovery is part of the task: before solving a complex problem manually, check whether Serena, PyCharm, a skill or an MCP offers a reliable specialized operation.** Read relevant skill instructions before implementing manually.
- Use the cheapest reliable source of truth. Prefer Serena/PyCharm structured symbol and inspection results when they target this checkout. Use shell for reproducible Codex CLI, Python, tests and Git operations.
- Keep `docs/TOOLS_CATALOG.md` and `docs/SKILLS_CATALOG.md` as dynamic discovery guidance, not fixed session inventories. `docs/ARCHITECTURE.md` describes the current implementation; verify runtime capabilities against the installed Codex CLI/schema.
- **OPENAI / CODEX SOURCE OF TRUTH:** for Codex CLI/exec/app-server, official SDKs, MCP, configuration, models, approvals, sandbox and protocol schemas, use this order: (1) installed CLI/schema when the installed version matters, (2) OpenAI Developer Docs MCP, (3) installed official source/docs, (4) official OpenAI web docs if needed. Never invent flags, fields, methods or capabilities. If official docs differ from the installed version, record the difference, follow the locally verified behavior and do not mark a capability IMPLEMENTED until verified locally. The Developer Docs MCP is a Codex development tool, not a P4-Codex-Bridge runtime dependency.
- Track MCP `SESSION_VISIBLE`, `CONFIGURED`, `ENABLED`, `CALLABLE`, `CHILD_VISIBLE` and `EFFECTIVE_FOR_RUN` separately; use unknown when evidence is missing. Profiles must deny external/destructive integrations by default and allow them only through verified, explicit policy.

## Implementation strategy

- Python is the sole canonical runtime and public API. Do not reintroduce a duplicate JavaScript Codex client or runtime.
- `codex exec` supports direct one-shot `run()` and managed/scheduled `start()`. The app-server runtime manager is resident and experimental; thread/turn state is distinct from exec runs. Schema preflight must fail closed for unknown required capabilities.
- No consumer integration until separately requested. Do not remove `P4-Planning-Agent/scripts/js` sources as part of bridge work.
- Profiles are configuration, not P4 business logic. Only `analysis` is implemented for one-shot `exec`; app-server turns accept explicit permissions. Planned profiles must fail closed rather than silently run with guessed policy.
- App-server approval handling is manual by default. Never auto-approve by default. `danger-full-access` plus automatic approval must never become a profile default; `AUTO_APPROVE_SAFE_ONLY` stays planned until action classification is deterministic.
- Preserve the distinction between `exec stop/kill` and app-server `turn/interrupt`; do not terminate Codex processes not owned by the bridge.

## Security and subprocesses

- Use argument arrays with `shell=False`; never concatenate a shell command or put prompt text in argv. Send prompt on stdin.
- Validate absolute existing cwd, canonicalize it and enforce configured allowed roots. Keep bridge cwd policy distinct from Codex sandbox permissions.
- Use only official Codex ChatGPT login. Never require/pass `OPENAI_API_KEY`; never read Codex auth/token/cookie files or print environment variables.
- Allowlist child environment, bound input/output and timeout, redact stdout-derived result/stderr, and clean temporary schema/result files. Never manage a Codex PID unless its bridge registry record and process creation identity match.
- stdout for Python CLI is JSON only; technical diagnostics on stderr must be sanitized. Tests use fake Codex by default. Never run Jira or E2E as tests.
- Result files can contain sanitized generated output until consumed by `read_result()`. Managed pending jobs can store bounded prompt payloads in SQLite until claim/cancellation; registry metadata must not contain credentials or environment values.
- Persist only sanitized lifecycle and approval state by default; do not persist message deltas/tool payloads. Unknown app-server requests must fail closed, never be accepted by a generic handler.

## Tests and validation

- Python: `python -m compileall -q p4_codex_bridge tests_py`, then `python -m unittest discover -s tests_py -v`.
- Real Codex smokes remain manual and separate: `python tests_real/smoke_streaming.py` is one minimal read-only turn; `python tests_real/smoke_approval_reject.py` is never run automatically.
- Do not claim checks passed unless they ran. Do not use an unrelated global Python project environment; `.venv` is not currently part of this checkout.

## Git

Review `git status` before broad edits and `git diff` before commit. No push, remotes, history rewrites, or commits unless explicitly requested. If a sandbox blocks `.git`, report the restriction and use an authorized normal-user environment; do not change ACLs or global safe-directory configuration.

## References

- [Tool catalog](docs/TOOLS_CATALOG.md), [skill catalog](docs/SKILLS_CATALOG.md)
- [Architecture](docs/ARCHITECTURE.md), [Python API](docs/PYTHON_API.md), [lifecycle](docs/LIFECYCLE.md), [capability matrix](docs/CAPABILITY_MATRIX.md)
- [Events](docs/EVENTS.md), [approvals](docs/APPROVALS.md), [feature catalog](docs/FEATURE_CATALOG.md), [test catalog](docs/TEST_CATALOG.md), [token budget](docs/TEST_TOKEN_BUDGET.md), [development workflow](docs/DEVELOPMENT_WORKFLOW.md)
