# Test token budget

## Policy

All automated tests in this phase are ZERO_TOKEN: use Python unit tests or fake CLI/app-server executables. Python unittest discovery must never contact Codex, Jira, or other external services.

## Current verification split

- Automated unit, fake-protocol, lifecycle, persistence, approval, CLI contract and packaging tests: zero Codex tokens.
- Real smoke scripts under `tests_real/`: separate manual tests; each intentionally uses one minimal Codex turn. They are excluded from normal test commands.
- Real approval smoke: manual only, never part of automated verification.
- Runtime manager fake-protocol tests: zero-token; no real server or model request.
- Phase 6 thread resume/fork/steer, terminal-state reconciliation, runtime approvals, timeout and stale-approval recovery tests: zero-token fake app-server.

The automated suite therefore uses **0 real Codex turns**. Manual smoke budgets:

| Smoke | Maximum inference turns | Expected relative cost | Usage reporting |
|---|---:|---|---|
| Structured output | 1 | LOW; one boolean field | Report provider usage when CLI exposes it; this exec response does not currently guarantee a usage breakdown |
| AGENTS marker | 1 per policy (`isolated`, `project`, `explicit`) | LOW prompt/output; system/context can dominate | Current CLI wrapper reports no reliable prompt/system/tool/MCP split |
| MCP visibility | 0 | No inference; diagnostic app-server may initialize configured servers | Report server/tool descriptor counts only, never auth material |
| Existing streaming smoke | 1 | Historically unexpectedly high aggregate input | App-server token usage may provide aggregate input, cached input, output, reasoning; it does not attribute system, tools, MCP descriptions, or AGENTS separately |
| Persistent-thread A/B smoke | 2 | LOW prompt/output; app-server setup overhead is not known | Historical script variant; not the current validation |
| Runtime approval smoke | At most 1 | LOW prompt/output; action fixture must remain inside isolated approval workspace | Manual only; do not run automatically; record request/reject/no-file effect |
| Persistent thread resume/fork smoke | 3 | Prompt/output are short; Codex context/tool overhead dominates | Executed once: A initial, A after resume, A on fork. Usage reported 50,493 total tokens (50,478 input, 38,144 cached input, 15 output, 0 reasoning); 14.1 s |
| Runtime approval reject smoke | 1 | Short confined file request under read-only sandbox | Executed once: pending request, `WAITING_APPROVAL`, reject, no file; 18,267 reported total tokens (18,240 input, 17,152 cached input, 27 output, 0 reasoning); 10.7 s |
| Live watch smoke | 1 | LOW prompt/output; app-server setup overhead is not known | Manual only; proves persisted start/delta/completion observation, reports usage when available |

The earlier ~16k-token `OK` smoke reported approximately 16,450 input tokens (about 11,008 cached), 5 output and 0 reasoning. The available counters did not separate system/context, tool schemas, MCP descriptions, AGENTS or reasoning input; precise attribution is unavailable. Later smokes should use isolated/read-only context, no unnecessary MCP servers where config allows, one short prompt, and one turn. Do not claim savings or a breakdown without usage data.

Other Phase 4 smokes remain scripts only and were not run in this validation. The approval smoke had one earlier cleanup failure before its SQLite state was moved outside the IDE-indexed fixture; its turn usage was not captured. Do not include that unobservable turn in token totals.

## MCP / skills / AGENTS effective-behavior phase

| Check | Inference turns | Model | Outcome / usage |
|---|---:|---|---|
| Local `model/list` discovery | 0 | N/A | `gpt-6-luna` listed; account entitlement not verified. |
| OpenAI Developer Docs MCP harmless search/fetch | 0 | N/A | Callable in host session; no model inference. |
| `mcpServerStatus/list`, `skills/list`, `config/read` diagnostics | 0 | N/A | App-server diagnostics only; no model call. Startup for Serena/PyCharm timed out; no side-effect tools invoked. |
| AGENTS marker smoke | 0 | Requested model would be `gpt-6-luna` | Not run: child MCP isolation cannot be guaranteed by this CLI/Bridge configuration. |
| MCP/skills child invocation smoke | 0 | Requested model would be `gpt-6-luna` | Not run: would require a model run with an unfiltered external tool surface. |

MCP/skills/AGENTS phase snapshot (before the later 1.0 daemon smoke): model ID `gpt-6-luna` was listed by installed `model/list`; account entitlement and effective model were then **NOT_CONFIRMED** because no inference had been attempted. That phase used 0 turns. The subsequent 1.0 daemon turn is recorded separately below. No fallback model was used. The manual AGENTS script requires explicit `--allow-unfiltered-mcps`, uses this exact model, and reports effective model/usage as unverified where the surface does not expose them.

## Commands

```powershell
python -m unittest discover -s tests_py -v
python -m unittest discover -s tests_py -v
python tests_real/smoke_streaming.py
```

Do not add live calls to `setUp` or ordinary unit tests. Keep auth and rate-limit verification in manual scripts with fixed, low-cost prompts.
# Resource scheduler phase

- Automated JS/Python suites and the 50-job fake stress scenario: ZERO_TOKEN.
- `tests_real/smoke_concurrency.py`: manual only, two minimal turns; not run by the suite.

# Resident service phase

- Python/JavaScript regression suites, fake foreground service lifecycle, local SQLite control requests, retention cleanup, compatibility gates, wheel/editable builds, and config validation: ZERO_TOKEN. They do not invoke Codex inference, Jira, MCP tools, or external network services.
- Packaging diagnostic: wheel data installs `Scripts/p4-codex.cmd` beside the environment interpreter. Module invocation and the wrapper contract passed offline tests. P4 and an independent minimal generated console-script `.exe` both hung in Windows diagnostics; cause not established. No inference was run.
- After the launcher wrapper and doctor reporting changes, `compileall` and the combined offline suite passed: 18 JS + 128 Python tests (two opt-in Windows launcher diagnostics skipped). All were zero-token. The five consecutive earlier runs were performed before these wrapper changes.
- `tests_real/smoke_service.py`: manual only, one short turn; never part of automated tests. The final 1.0 release smoke requested Luna after catalog discovery; the effective model remained unverified.
- At the time of this service-phase snapshot, no real daemon smoke had executed; the later 1.0 smoke is recorded below.
- Audit additions use only fake CLI/protocol and local SQLite fixtures; no real turns or tokens were used.

## Final 1.0 release gate (2026-10-07)

- DB migration interruption, bounded-lock, corruption and cleanup tests use
  local SQLite fixtures: ZERO_TOKEN.
- Clean wheel/sdist builds and temporary-environment install/CLI validation:
  ZERO_TOKEN.
- Final daemon service smoke: at most one turn, exact model `gpt-6-luna`, no
  fallback. It is gated on model catalog presence, offline regression and
  explicit acknowledgement that app-server cannot filter inherited MCPs.
- Never count model catalog presence as entitlement. Report effective model
  and token usage as unverified if Codex does not expose those values.
- Final offline regression after the smoke config regression fix: 5 consecutive
  runs, 164 tests each, 2 opt-in Windows `.exe` diagnostics skipped each time;
  compileall PASS; zero inference in automated tests.
- Final package wheel/sdist build and install, config validation, doctor,
  service-status and model catalog probes used no model turn. The service smoke
  used exactly one turn with requested model `gpt-6-luna` and completed in
  11.045 seconds. Codex did not expose input, cached input, output, reasoning,
  total usage, or effective-model identity through the bridge; those values are
  `NOT_CONFIRMED`, not zero. The smoke's first attempt failed config validation
  before service startup and made no inference.
