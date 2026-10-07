# P4-Codex-Bridge 1.0 release checklist

This is the release gate, separate from phase history. A version becomes 1.0.0
only after every **Required** item is PASS or an explicit release owner accepts
the recorded limitation. `NOT_CONFIRMED` is not evidence of support.

## Required gates

| Area | 1.0 criterion | Release status | Evidence / accepted boundary |
|---|---|---|---|
| Public Python API | Stable exports and exceptions documented; experimental lifecycle APIs labeled | DONE | Exact package exports and `CodexBridge.run` signature tested; manager internals stay internal. |
| CLI | Stable commands, JSON output for automation, read-only/state-changing boundary | DONE | Parser tree, JSON/JSONL modes and exit map documented and tested. |
| Editable package / wheel / sdist | Install and invoke supported entry points | DONE | Clean wheel and sdist; isolated wheel install; module and `.cmd` launchers, metadata and CLI checks passed. |
| Foreground service | Start, health, cross-process submit/watch and graceful stop | DONE | One real installed-wheel daemon turn passed. Native SCM integration is OUT_OF_SCOPE. |
| `exec` backend | Typed operations, validation, timeout, cancellation and feature gates | DONE | Offline coverage and capability gates; individual exec resume/fork/review real-smoke coverage is not a 1.0 requirement. |
| `app-server` backend / persistent threads / approvals | Supported local lifecycle surface with explicit capability limits | DONE | One real create/start daemon path passed; resume/fork and approval reject have prior real evidence. Protocol remains experimental. |
| Cross-backend scheduler | Shared queue, limits, cancellation and workspace locks | DONE | Mixed-backend offline scheduler/stress coverage. Real contention is not claimed. |
| Recovery | Reconcile only with evidence; never replay uncertain work | DONE | Conservative reconciliation is tested. No safe exec readoption or automatic transport reconnect: KNOWN_LIMITATION. |
| Observability | `ps`, inspect, watch, health, metrics and doctor | DONE | Cross-process journal/control tested offline; daemon smoke verified watch and cleanup. Remote delta replay is unavailable: KNOWN_LIMITATION. |
| Config / version / capability gates | Strict TOML/env precedence, schema discovery and feature preflight | DONE | Contract frozen and tested; app-server required methods remain `SUPPORTED_WITH_LIMITATIONS`. |
| Retention / DB migrations | Effective cleanup, atomic migration and health checks | DONE | Fault matrix and preservation tests pass. Physical disk-full and power-loss remain uninduced and documented. |
| Security | Fail closed when state is unknown; explicit acknowledgement for unfiltered trusted runs | DONE | No claim of MCP isolation. Per-run MCP filtering is NOT_SUPPORTED_BY_CODEX and is a KNOWN_LIMITATION. |
| Offline suite | Five full consecutive release-candidate passes plus final version check | DONE | Python 3.13.3: RC compileall and 164 tests PASS in five consecutive runs (two opt-in `.exe` diagnostics skipped); after the version bump/test expectation update, compileall and the final 164-test suite PASS once. No inference in tests. |
| Final package / daemon smokes | Clean artifact install and selected real smoke | DONE | Wheel/sdist built; doctor/config/service checks passed. One Luna-requested daemon turn returned `OK`; effective model and token usage are NOT_CONFIRMED. |
| Python canonical runtime / JS removal | One implementation for new consumers | DONE | Independent JS runtime/package/tests removed; no consumer files changed. |
| Windows console-script `.exe` | Optional generated launcher | KNOWN_LIMITATION | P4 and independent minimal launcher hang in the observed environment; cause is unknown. Module and `.cmd` launchers passed. |
| Consumer integration / native Windows SCM | Not required for this release | OUT_OF_SCOPE | No P4 consumers modified; supervisors/SCM deployment remain outside this package release. |

## Status vocabulary

- `DONE`: required release gate passed. It does not upgrade a capability's
  evidence state in `CAPABILITY_MATRIX.md`.
- `KNOWN_LIMITATION`: accepted boundary is documented and does not block this release.
- `OUT_OF_SCOPE`: not part of the 1.0 package contract.
- `IMPLEMENTED`: bridge behavior exists and has direct offline coverage; real
  execution evidence is tracked separately in the capability matrix.
- `PARTIAL`: capability-level evidence or behavior has a defined gap; this may
  remain while the release gate is DONE with an accepted limitation.
- `NOT_CONFIRMED`: available evidence cannot establish behavior.
- `NOT_SUPPORTED`: verified surface does not provide the operation, or Bridge
  deliberately rejects it.

## Release record

All required release gates are complete. Accepted limitations and evidence are
recorded above, in `CONTRACT_1_0.md`, and in `CAPABILITY_MATRIX.md`.
