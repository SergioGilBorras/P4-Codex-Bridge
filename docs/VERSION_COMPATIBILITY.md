# Runtime compatibility

**Bridge source version:** `1.1.0`. It is installed from source or a locally built distribution unless a separately verified package publication is available.

- Supported Python runtime: **3.10+** (Python 3.10 uses `tomli` for TOML compatibility).
- The bridge uses the installed **Codex CLI**, not a direct OpenAI Responses API integration.
- Codex CLI features and app-server methods are checked using the installed CLI help, generated local schema and/or live protocol handshake. A matching version string alone is not authoritative.
- The app-server protocol remains experimental. Generated schema presence can mean “supported with limitations”; a successful matching RPC is stronger evidence.
- CLI model discovery does not confirm the account can invoke every listed model.

## Git repository check

`CodexBridge.run()` and managed `CodexBridge.start()` accept `skip_git_repo_check: bool = False`. When `True`, the bridge checks for `--skip-git-repo-check` in installed `codex exec --help` and raises `CapabilityUnavailableError` before execution/submission if absent. When `False`, existing CLI behavior is unchanged. This opt-in is not supported by `resume()`, `fork()`, `review()`, cross-process service-client submissions or the bridge CLI JSON contract.

Check support without inference:

    codex --version
    codex exec --help
    python -m p4_codex_bridge capabilities

For the intended execution security policy and the distinction between discovery and effectiveness, see [security](SECURITY.md) and [capability matrix](CAPABILITY_MATRIX.md).

## Portable behavior

Windows supports module invocation and a `.cmd` wrapper; generated console-script `.exe` behavior depends on the environment. On Linux/macOS, use the current Python interpreter and installed CLI. See [installation](INSTALLATION.md) and [known limitations](KNOWN_LIMITATIONS.md).
