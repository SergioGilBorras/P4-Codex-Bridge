# Known limitations

## Windows generated console-script executable

**Classification:** environment/toolchain limitation; non-blocking for the
supported Windows entry points.

In diagnostics performed on 2026-10-07, P4's module invocation and a `.cmd`
wrapper invoking the module worked, while the generated `p4-codex.exe` hung
before output. An independent, minimal `tiny-launcher` package built with the
same packaging stack showed the same behavior. Its Python callable worked and
its generated executable hung. This is evidence against a P4-specific defect,
but does not identify the cause. No attribution is made to setuptools, Windows,
antivirus or sandboxing.

Diagnostic environment: Python 3.13.3 x64, Windows 10 build 19045, pip 26.2.1,
setuptools 84.0.0 and wheel 0.48.0.

On Windows use `python -m p4_codex_bridge ...` with the intended interpreter or
the installed `Scripts\p4-codex.cmd` wrapper. The automatically generated
console-script `.exe` remains optional and environment-dependent. `doctor` does
not execute it because a hang cannot be safely bounded without managing its
entire descendant process tree.

Decision record: [ADR-001](adr/ADR-001-windows-console-script-launcher.md).
