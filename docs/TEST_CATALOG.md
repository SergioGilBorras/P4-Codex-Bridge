# Test catalog

All automated tests are offline. They use fake CLI/app-server processes, local
SQLite databases and temporary fixtures; no Codex inference, Jira or external
MCP action is performed.

## Automated commands

| Command | Scope |
|---|---|
| `python -m compileall -q p4_codex_bridge tests_py` | Syntax compilation of runtime and tests |
| `python -m unittest discover -s tests_py -v` | Python unit, fake integration, lifecycle, service, security, capability, packaging helper and API contract tests |
| `python tests_py/test_windows_launcher_install.py` | Optional Windows wheel/launcher diagnostic; excluded from ordinary discovery because the generated `.exe` can hang in affected environments |

The JavaScript runtime, `package.json`, Node tests and npm workflow were removed
as part of the single-runtime decision. The Python implementation is canonical.
The old `P4-Planning-Agent/scripts/js` files are outside this repository and
were not changed.

## Focused coverage

- `test_bridge.py`, `test_exec_advanced.py`: direct and managed exec, typed
  `skip_git_repo_check` propagation/capability failure, resume,
  fork, review, structured output, last-message files, timeout, process
  ownership, queue dispatch, cancellation and result redaction.
- `test_runtime_manager.py`, `test_app_server_events.py`: fake JSON-RPC,
  threads/turns, events, approvals, recovery and lifecycle handling.
- `test_scheduler.py`: ordering, backend/global/profile limits, workspace
  READ/WRITE locks, cancellation, recovery and bounded fake stress.
- `test_service.py`, `test_service_client.py`: TOML validation, SQLite command
  channel, typed requests, idempotency, service lifecycle and diagnostics.
- `test_security_and_capabilities.py`: trust/risk policy, fail-closed unknown
  MCP state, isolation rejection, schema parsing and capability status.
- `test_public_api.py`: exact package-root export set; private scheduler,
  registry, transport and service implementation types must stay unexported.
- `test_windows_cmd_launcher.py`: supported module/cmd entrypoint generation,
  quoting, argument forwarding and exit-code behavior.

## Manual real smokes

Manual scripts under `tests_real/` are excluded from automated test commands.
Existing real evidence is recorded in `docs/CAPABILITY_MATRIX.md` and is not
repeated by this suite. No smoke is run as part of API/security preflight.

## Release repeatability

The release-candidate offline gate was compileall plus the complete Python
unittest suite, repeated five consecutive times. The final 1.0.0 version bump
was followed by one full suite pass. The generated Windows console-script
`.exe` remains an opt-in diagnostic; supported Windows entry points are
`python -m p4_codex_bridge` and the packaged `p4-codex.cmd` wrapper.

## DB and packaging closeout tests

- `test_interrupted_schema_migration_rolls_back_and_retries` injects a DDL
  failure, verifies the old version is preserved, then retries successfully.
- `test_locked_database_migration_fails_with_bounded_timeout_then_recovers`
  verifies a two-second bounded lock failure and clean retry.
- `test_corrupt_database_health_is_read_only_and_reports_recovery_action`
  confirms corruption reporting leaves the database bytes unchanged.
- `test_cleanup_dry_run_and_clean_preserve_active_lost_and_pending_approval`
  verifies retention exclusions using synthetic rows.
- Wheel/sdist installation checks and their CLI probes are offline and do not
  execute Codex inference.
- Release-candidate gate on 2026-10-07: `compileall` PASS and 164 tests PASS
  in five consecutive runs; two opt-in Windows `.exe` diagnostic tests skipped
  in each run. After the 1.0.0 bump and stale assertion updates, final
  `compileall` and the 164-test suite passed once. Clean wheel/sdist build,
  final wheel install, module/CMD CLI, config validation, service status and
  elevated doctor passed.
- Manual daemon smoke: one cross-process submit using the installed wheel,
  read-only watch, exact final `OK`, graceful service stop, and zero remaining
  runs/queue/locks/approvals/payloads. Requested `gpt-6-luna`; effective model
  and token usage were not exposed. The first attempt stopped at invalid smoke
  TOML before daemon startup and made no inference; a regression test now checks
  the config section and the corrected smoke passed once.
