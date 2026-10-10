# Installation

## Requirements

- Python **3.11+**. Bridge 1.2.0 drops Python 3.10 support because it now uses the standard-library `StrEnum` and `tomllib` APIs and depends on `portable-tempdirs`.
- `portable-tempdirs` 0.1.2 is pinned to Git commit `fd6dbd640630e6911a53b4d756089099ec870a8b`; install therefore requires Git and access to that repository unless the dependency has been prebuilt and provided through an approved offline package source.
- Installed official Codex CLI, available to the same operating-system user and process environment that runs the bridge.
- Codex authentication through `codex login` or another CLI-supported mechanism. The bridge does not require `OPENAI_API_KEY` or access Codex login tokens.
- A directory for `cwd` that already exists and passes optional `allowed_roots` checks. Git is not required if the caller explicitly uses the supported `skip_git_repo_check` option.

Some Codex CLI distributions use Node.js internally; install dependencies required by the selected official CLI package.

## Install this source checkout

Use the intended Python environment, preferably a virtual environment:

    python -m pip install -e .
    python -m p4_codex_bridge --version
    python -m p4_codex_bridge --help

Source package version: **1.2.0 (development, not published)**. Installing from this checkout is not equivalent to publishing a release to a package index.

The fixed Git dependency avoids moving-branch resolution. The dependency is installed from an immutable source commit; this does not make Bridge distributions self-contained offline. Because project metadata declares a direct Git URL, do not upload these distributions to PyPI unless the dependency is replaced by a published, verified release and the resulting metadata is checked.

Preflight the external Codex CLI independently (no model call):

    codex --version
    codex login status
    codex exec --help
    python -m p4_codex_bridge capabilities

The output of `codex exec --help` must contain `--skip-git-repo-check` for callers that request `skip_git_repo_check=True`.

## Windows invocation

Prefer the interpreter selected for installation:

    python -m p4_codex_bridge --version

The installed `Scripts\p4-codex.cmd` wrapper also selects the adjacent Python interpreter:

    & .\.venv\Scripts\p4-codex.cmd --version

The packaging-generated `p4-codex.exe` may not work reliably in every Windows toolchain; it is optional. Avoid using the generated executable as the only service or automation entry point. `doctor` does not launch it automatically.

## Configuration and local service

The local foreground service uses explicit TOML validation and a same-user state directory:

    python -m p4_codex_bridge config validate --config C:\P4\config\p4-codex.toml
    python -m p4_codex_bridge doctor --json --config C:\P4\config\p4-codex.toml

These commands inspect configuration/capabilities; they do not run inference by themselves. Starting a service requires further operator choice. See [configuration](CONFIGURATION.md), [service](SERVICE.md), [security](SECURITY.md) and [known limitations](KNOWN_LIMITATIONS.md).

## Development tests

    python -m compileall -q p4_codex_bridge tests_py
    python -m unittest discover -s tests_py -v

The ordinary suite runs fake CLI and app-server processes; real scripts under `tests_real/` require separate consent.
