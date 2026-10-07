# ADR-001: Windows console-script launcher

- **Date:** 2026-10-07
- **Status:** Accepted

## Context

The package's `console_scripts` executable (`p4-codex.exe`) hung before output
in Windows diagnostics. `python -m p4_codex_bridge` and a `.cmd` wrapper worked.
A separate minimal package built with the same Python 3.13.3 x64, setuptools
84.0.0 and wheel 0.48.0 also had a working Python callable and a hanging
generated executable. The evidence does not identify a lower-level cause.

## Decision

The automatically generated `.exe` is **optional and environment-dependent**;
it is not a requirement for P4-Codex-Bridge 1.0 operation or release. Supported
Windows entry points are:

1. `python -m p4_codex_bridge`, using the intended interpreter;
2. the project's `p4-codex.cmd`, installed beside the environment's
   `python.exe` and invoking that interpreter.

Keep `[project.scripts] p4-codex` for environments where the generated launcher
works. Do not make it the only Windows entry point.

## Consequences

- The `.cmd` wrapper is included in the wheel's `Scripts` directory.
- The wrapper fails with a clear message if its adjacent `python.exe` is absent;
  it does not silently select a different interpreter from `PATH`.
- `doctor` reports the module entry point, `.cmd` availability and `.exe`
  presence separately. It never executes the potentially hanging `.exe`.
- The `.exe` diagnostic remains opt-in. This decision can be revisited when
  reproducible evidence identifies a concrete packaging/toolchain correction.

## Validation evidence

The independent tiny-launcher reproduction establishes that the observed hang
is not unique to P4. It does not prove whether the cause is packaging, toolchain
or environment behavior, so no more specific cause is recorded.
