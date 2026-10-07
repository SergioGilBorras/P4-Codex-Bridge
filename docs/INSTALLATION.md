# Installation

The package supports Python 3.10 and newer. Python 3.10 installs the small
`tomli` compatibility dependency; newer Python uses stdlib `tomllib`.

From a checkout:

```powershell
python -m pip install -e .
python -m p4_codex_bridge --version
python -m p4_codex_bridge config validate --config C:\P4\config\p4-codex.toml
python -m p4_codex_bridge doctor --config C:\P4\config\p4-codex.toml
```

On Windows, the recommended invocation is `python -m p4_codex_bridge ...` using
the intended environment's Python. The wheel also installs
`Scripts\p4-codex.cmd` when installed into a virtual environment. This wrapper
uses the `python.exe` beside itself, preserving the environment selection and
paths containing spaces:

```powershell
& .\.venv\Scripts\p4-codex.cmd --version
```

The generated `Scripts\p4-codex.exe` remains available where its console-script
launcher works, but it is optional and environment-dependent. It is not the
only supported Windows entry point.

`pyproject.toml` defines the `p4-codex` entry point and takes the version from
`p4_codex_bridge.__version__`. No consumer project was installed or modified.
Python is the only supported runtime. There is no JS/npm compatibility runtime in this repository; the existing consumer source files were left untouched.

## Historical launcher diagnostic

The launcher investigation was performed before the 1.0.0 release, while the
package reported version `0.3.0`. Its results are historical and the limitation
below still applies to generated console-script executables.

### Windows console-script launcher diagnostic

Diagnostic context: 2026-10-07, Python 3.13.3 x64, Windows 10 build 19045,
pip 26.2.1, setuptools 84.0.0 and wheel 0.48.0. `python -m p4_codex_bridge
--version` and a `.cmd` wrapper invoking the same module passed, while the
packaging-generated `p4-codex.exe --version` hung before output. An independent
minimal `tiny-launcher` package built with the same packaging stack behaved the
same way: its Python callable passed and its generated `.exe` hung. This is
classified as an **environment or toolchain limitation**, with no evidence of
a P4-specific defect. The precise cause is unknown; no attribution is made to
setuptools, antivirus or Windows.

Supported Windows routes are the module invocation and the installed
`p4-codex.cmd` wrapper. The `.exe` is optional/environment-dependent. See
[Known limitations](KNOWN_LIMITATIONS.md) and
[ADR-001](adr/ADR-001-windows-console-script-launcher.md).

The opt-in diagnostic `P4_RUN_WINDOWS_LAUNCHER_TESTS=1` still checks the
packaging-generated `.exe` in an isolated wheel/venv, but is not part of normal
tests and is not a release requirement. The bridge doctor does not execute this
launcher automatically.

## 1.0.0 release install verification

The final 1.0.0 wheel and sdist built from a clean artifact tree. The wheel was
installed in a fresh temporary venv; distribution metadata and
`p4_codex_bridge.__version__` report `1.0.0`. Module invocation, `--help`,
`config validate`, `doctor --json`, `service status --json`, and the installed
`Scripts\p4-codex.cmd` passed. The final daemon smoke also ran from the installed
wheel. No inference is performed by package build/install or doctor checks.
potentially hanging launcher; it reports its status as unverified.

The earlier editable-install timeout came from using the unrelated
`GestorProyectosIA` virtual environment, whose setuptools build backend was
missing. It was not a setuptools hook timeout in this project. Recheck clean
environments with their own Python and build backend; do not select a Python
environment through a neighboring P4 project.

An editable install is local to the selected Python environment. Use the same
interpreter for install and service supervision. Do not install the package into
the consumer repositories as part of this phase.
