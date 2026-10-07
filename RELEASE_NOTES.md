# Release notes

## 1.0.0

First stable local release of P4-Codex-Bridge. Python is the canonical runtime
and public consumer API.

### Included

- `codex exec` operations with typed requests, validation, bounded subprocess
  handling, structured output support, result collection and capability gates.
- An app-server backend for persistent threads and turns, streaming lifecycle
  events, thread resume/fork, steering where supported, and manually managed
  approvals.
- One persistent resource scheduler shared by managed exec and app-server work:
  queueing, cross-backend limits, resource priority, workspace READ/WRITE locks,
  cancellation and conservative recovery.
- A foreground Windows-ready service, singleton ownership, startup recovery,
  SQLite-backed control channel, typed `CodexServiceClient` submissions and
  cross-process thread/turn creation.
- Operational discovery and control through `ps`, `inspect`, read-only `watch`,
  `resources`, `health`, `metrics`, `doctor`, approvals and maintenance commands.
- Strict TOML/environment configuration, capability preflight, security gates,
  DB health, transactional migrations and configurable retention.
- Wheel and sdist packaging, `python -m p4_codex_bridge`, and the installed
  Windows `p4-codex.cmd` launcher.

### Verification

- Python 3.13.3 release-candidate suite: 164 tests passed in five consecutive
  runs; two opt-in Windows console-script `.exe` diagnostics were skipped each
  run. After the version bump and test expectation update, the final 164-test
  suite passed once.
- `compileall`, clean wheel/sdist builds, isolated wheel install, module/CMD
  entry points, config validation, doctor and service status passed.
- One installed-wheel daemon smoke requested `gpt-6-luna` and returned exact
  `OK`. The effective model and token usage were not exposed by Codex and are
  not asserted.

### Known limitations

- Codex does not provide a verified per-run MCP filter here. The bridge does
  not claim isolation; it rejects unknown or unacknowledged unsafe states and
  requires explicit risk acknowledgement for a trusted unfiltered override.
- Effective child behavior for `AGENTS.md` and skills is not confirmed.
- Recovery is conservative: no safe exec child readoption, no automatic
  app-server transport reconnection, and uncertain work is not replayed.
- Remote replay of message deltas and safe interactive attach are unavailable.
- The generated Windows console-script `.exe` can hang in some environments;
  its cause is unknown. Use the module entry point or installed `.cmd` wrapper.
- Effective model identity and usage/token breakdown can be unavailable from
  the app-server surface.

### Out of scope

- P4 consumer integration, remote/distributed scheduling, and native Windows
  Service Control Manager integration.
