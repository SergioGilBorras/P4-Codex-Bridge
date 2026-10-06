# Test token budget

## Policy

More than 99% of automated tests for this phase must be ZERO_TOKEN: use pure Python unit tests or a fake app-server executable. `npm test` and Python unittest discovery must never contact Codex, Jira, or other external services.

## Current verification split

- Automated unit, fake-protocol, lifecycle, persistence, approval and legacy JS tests: zero Codex tokens.
- Real smoke scripts under `tests_real/`: separate manual tests; each intentionally uses one minimal Codex turn. They are excluded from normal test commands.
- Real approval smoke: manual only, never part of automated verification.
- Runtime manager fake-protocol tests: zero-token; no real server or model request.

The automated suite therefore uses **0 real Codex turns**. Manual smoke budgets:

| Smoke | Maximum inference turns | Expected relative cost | Usage reporting |
|---|---:|---|---|
| Structured output | 1 | LOW; one boolean field | Report provider usage when CLI exposes it; this exec response does not currently guarantee a usage breakdown |
| AGENTS marker | 1 per policy (`isolated`, `project`, `explicit`) | LOW prompt/output; system/context can dominate | Current CLI wrapper reports no reliable prompt/system/tool/MCP split |
| MCP visibility | 0 | No inference; diagnostic app-server may initialize configured servers | Report server/tool descriptor counts only, never auth material |
| Existing streaming smoke | 1 | Historically unexpectedly high aggregate input | App-server token usage may provide aggregate input, cached input, output, reasoning; it does not attribute system, tools, MCP descriptions, or AGENTS separately |
| Runtime manager smoke | 1 | LOW prompt/output; app-server setup overhead is not known | Manual only; records protocol lifecycle, latency and usage if returned |
| Live watch smoke | 1 | LOW prompt/output; app-server setup overhead is not known | Manual only; proves persisted start/delta/completion observation, reports usage when available |

The earlier ~16k-token `OK` smoke reported approximately 16,450 input tokens (about 11,008 cached), 5 output and 0 reasoning. The available counters did not separate system/context, tool schemas, MCP descriptions, AGENTS or reasoning input; precise attribution is unavailable. Later smokes should use isolated/read-only context, no unnecessary MCP servers where config allows, one short prompt, and one turn. Do not claim savings or a breakdown without usage data.

Phase 4 smokes are scripts only and have not been run as part of implementation, so new real-token usage is **0**.

## Commands

```powershell
python -m unittest discover -s tests_py -v
npm test
python tests_real/smoke_streaming.py
```

Do not add live calls to `setUp`, ordinary unit tests, or `npm test`. Keep auth and rate-limit verification in manual scripts with fixed, low-cost prompts.
# Resource scheduler phase

- Automated JS/Python suites and the 50-job fake stress scenario: ZERO_TOKEN.
- `tests_real/smoke_concurrency.py`: manual only, two minimal turns; not run by the suite.
