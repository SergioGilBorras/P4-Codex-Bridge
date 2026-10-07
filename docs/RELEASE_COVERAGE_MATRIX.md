# Public feature to verification matrix

This map records the primary offline evidence and real-smoke evidence. It is
not a line-coverage claim.

## 1.0 contract closeout additions

| Contract/capability | Implementation | Offline coverage | Current runtime evidence |
|---|---|---|---|
| App-server schema snapshot and RPC map | Generated-local schema classification, SHA-256 compact snapshot, schema/runtime evidence separated | Known/missing/renamed/extra/malformed/unavailable schema fixtures | Local generator verified on 2026-10-07: Codex 0.160.1, 262 protocol method names, SHA-256 `4a02439823bc98fbbca86d9f934d5a90a638b41ec16c635c8c4448b2b9e14867`; runtime support remains separately gated |
| Public API / CLI / config freeze | Explicit exports and closed `run` signature; parser tree; strict TOML and prefixed env variables | Export/signature/tree/exit-code/config tests | No inference required |
| MCP security boundary | Per-run filter is NOT_SUPPORTED; UNKNOWN fails closed, explicit trusted risk acknowledgement remains unfiltered and warns | Direct, managed, runtime-manager, service request and daemon validation | No inference required; no isolation claim |
| DB migration fault matrix | Atomic runtime/service/scheduler migrations, bounded lock handling and fail-closed corruption/version handling | v1 migration, injected DDL interruption rollback/retry, bounded lock retry, corrupt DB read-only check, retention preservation | Physical disk-full/power-loss not induced; classified/documented in `DB_RECOVERY_MATRIX.md` |
| Wheel/sdist packaging | Clean-source wheel and sdist build; isolated installs and package content audit | Final temporary wheel venv: module version/help, config validation, CMD launcher, service status and elevated doctor | Doctor PASS: Codex/login/app-server available, generated local schema detected; service starts STOPPED. No inference during package checks |

| Public feature | Offline unit/fake coverage | Real smoke evidence | Gap |
|---|---|---|---|
| `CodexBridge.run/start`, structured output, last message, timeout, redaction | `tests_py/test_bridge.py`, `tests_py/test_exec_advanced.py` | Structured output and live watch passed previously | Direct/scheduled behavior is separate; Python-only offline suite is the release gate |
| `resume/fork/review`, local feature gate | `tests_py/test_bridge.py` | Persistent app-server thread resume/fork passed; exec variants not smoke-tested | Review/exec resume/fork real behavior not required yet |
| app-server create/start/resume/fork/steer/events/approval | `tests_py/test_runtime_manager.py`, `test_app_server_events.py` | Persistent thread and approval reject passed previously | Steer and approval accept not real-tested |
| queue, limits, workspace locks, cancellation, recovery | scheduler/runtime/client fake tests; scheduler stress demo | No real contention smoke | Real contention is optional for 1.0 only if documented as unverified |
| run discovery, inspect, read-only watch | `tests_py/test_bridge.py`, runtime/service tests | Live Watch passed previously | Full service process relaunch/replay limited |
| service singleton, stop/restart, SQLite control channel | `tests_py/test_service.py` | One installed-wheel foreground service turn; cross-process client submit and read-only watch; exact final `OK`; graceful stop | PASS on 2026-10-07. `gpt-6-luna` was requested and catalog-listed; effective model and usage were not exposed. No claim of token count or MCP isolation |
| config parsing/precedence/sanitization | `tests_py/test_service.py`, `tests_py/test_cli_contract.py` | N/A | Names/defaults/precedence are frozen in `CONTRACT_1_0.md`; no `config_version`, unknown keys fail |
| database health and maintenance cleanup | `tests_py/test_service.py::MaintenanceTests`, migration fault tests | N/A | Migration/locked DB and retention preservation boundaries are covered; physical disk-full/power-loss are documented but not induced |
| compatibility result model | `tests_py/test_compatibility.py` | N/A | Broader version matrix and app-server preflight gates remain partial |
| CLI/package installation | service/parser tests; packaging checks | N/A | Module invocation and installed `.cmd` are supported; `.exe` is an environment/toolchain limitation demonstrated by the independent tiny launcher |
| MCP/skills/AGENTS child effectiveness | fixtures in bridge tests | No matching `exec` run receipt | Keep NOT_CONFIRMED; no runtime decision may depend on presumed visibility |
| SECURITY boundaries | redaction, permission, process identity tests | N/A | No per-run MCP filtering; ACL protection is operator responsibility |

Run zero-token checks with `python -m compileall -q p4_codex_bridge tests_py`
and `python -m unittest discover -s tests_py -v`. Release-candidate evidence:
five consecutive passes of 164 tests after the smoke-config regression fix
(two opt-in `.exe` diagnostics skipped per run). After the 1.0.0 bump and stale
assertion updates, final compileall and the 164-test suite passed once. There
is no Node/npm runtime.
# Cross-process request coverage

| Capability | Implementation | Offline coverage | Runtime evidence |
|---|---|---|---|
| Typed exec submit | Implemented through existing managed exec scheduler | Unit dispatch/validation tests | Fake facade route passed; Codex exec not invoked |
| Thread create / turn start | Implemented through resident manager | Unit routing and claim/recovery tests | Fake foreground daemon CLI flow passed: create, turn, ps, watch, stop |
| Idempotency / crash ambiguity | Implemented; claimed requests are not replayed | Unit tests | No inference required |
| Windows wheel console launcher | Module invocation and installed `.cmd` wrapper; `.exe` test is opt-in | Module passes; `.cmd` package path verified and its operation was confirmed outside the sandbox | Generated `.exe` remains environment/toolchain-limited; no cause established |
