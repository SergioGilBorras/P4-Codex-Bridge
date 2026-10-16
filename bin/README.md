# Windows command launcher

`p4-codex.cmd` is the Windows command wrapper installed into the Python environment's `Scripts` directory.

The wrapper locates `python.exe` beside itself (using `%~dp0`), runs `python -m p4_codex_bridge`, forwards every supplied argument (`%*`), and returns the Python command's exit code. If the adjacent Python executable does not exist, it prints a diagnostic and exits with code 9009.

It does not install Codex, start a service automatically, or run an inference merely by being invoked. The wrapper is distributed with the project wheel through `[tool.setuptools.data-files]`.

On Windows, use `.venv\Scripts\p4-codex.cmd --help` or `.venv\Scripts\python.exe -m p4_codex_bridge --help`. See [CLI documentation](../docs/CLI.md).
