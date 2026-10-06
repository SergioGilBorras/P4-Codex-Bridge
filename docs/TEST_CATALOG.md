# Test catalog

## Closeout additions

- `tests_py/test_scheduler.py`: scheduler ordering, cross-backend limits/locks, queue persistence and fake stress. `tests_py/test_bridge.py` additionally dispatches managed exec workers, verifies cross-backend workspace blocking, and checks active cancel/resource release.
- `tests_py/test_runtime_manager.py`: exec capacity release waking a queued app-server turn, concurrent `RunRegistry` schema initialization, and six immediate SQLite state-directory teardowns per test run.
- `tests/test_bridge.js`: fake CLI compatibility tests do not apply a fixed wall-clock cutoff to normal success cases; the bridge's own timeout behavior has a dedicated test. This avoids treating Windows process startup/load variance as a product timeout.
- `tests_py/scheduler_demo.py`: fake-only human UX fixture for `ps`, `inspect`, `watch`, `resources`, and queued `cancel`; it creates two active fake jobs plus workspace/global waiters. No Codex calls.

## Live observability

- `tests_py/test_bridge.py`: exec bridge IDs, managed dispatch/cancel, cross-backend workspace blocking, verified-result recovery, LOST reconciliation, sanitized metadata, native session resolution, ambiguity, completion inspection and repeatable watchers.
- `tests_py/test_runtime_manager.py`: app-server run IDs, metadata inheritance, native thread resolution, journal replay and independent watcher snapshots.
- `tests_real/smoke_live_watch.py`: manual one-turn real Codex smoke; excluded from all automated test commands.

| Command | Type | Live Codex | Coverage |
|---|---|---:|---|
| `python -m unittest discover -s tests_py -v` | Unit + fake CLI/app-server integration + lifecycle | No | Protocol/event/lifecycle/approval coverage plus CLI run/resume/fork/review, structured output parsing failures, last-message temp cleanup, policy/permission validation, process registry, and legacy Python behavior. |
| `node tests/test_bridge.js` | Legacy JS unit | No | Stable stdin/stdout contract, fake CLI, timeout, redaction and command-injection resistance. |
| `npm test` | Combined offline suite | No | 18 JS and 86 Python unittest cases; tested 5 consecutive times in the closeout run. |
| `python tests_real/smoke_streaming.py` | Manual real streaming smoke | Yes, one turn | Installed version/login, observed `TurnStarted`, message delta, `TurnCompleted`, exact final `OK`, latency and token usage if exposed. Read-only workspace. |
| `python tests_real/smoke_approval_reject.py` | Manual approval smoke; do not run automatically | Yes, at most one turn | Requests creation of one named file in the isolated `approval_workspace`, expects the approval event, rejects it, and verifies the file was not created. Read-only sandbox. |
| `python tests_real/smoke_structured_output.py` | Manual structured-output smoke | Yes, one turn | Small JSON response constrained by a one-field schema. |
| `python tests_real/smoke_agents_context.py --policy project` | Manual AGENTS child visibility smoke | Yes, one turn per policy invocation | Asks for exact marker in isolated fixture; accepts `isolated`, `project`, or `explicit`. Exact marker confirms effective instruction for that specific run. |
| `python tests_real/smoke_mcp_visibility.py` | Manual diagnostic inventory; no model turn | No inference turn | Queries `mcpServerStatus/list`; starts a diagnostic app-server and reports advertised state/tools, not tool callability or exec-run effectiveness. |
| `python tests_py/smoke_codex.py` / `node tests/smoke_codex.js` | Existing manual Phase 1 smokes | Yes | One-shot Python/legacy CLI behavior. |

All test functions and `npm test` use local fakes; they do not call Codex or Jira. Real smoke scripts are separate and excluded from automated commands. See [token budget](TEST_TOKEN_BUDGET.md), [events](EVENTS.md) and [approvals](APPROVALS.md).
# Resource scheduler tests

`tests_py/test_scheduler.py` verifies queue ordering, atomic competing claims, limits, READ/WRITE workspace exclusion, cancellation, restart reconciliation, canonical paths and 50 fake jobs. It does not start Codex and consumes zero tokens. The two-turn concurrency smoke is manual at `tests_real/smoke_concurrency.py` and was not executed.
