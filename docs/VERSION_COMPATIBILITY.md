# Runtime compatibility

**Bridge source version:** `1.3.0` development. It is installed from source or a locally built distribution; this feature has not been published as a release.

- Supported Python runtime: **3.11+**. The 1.2.0 line dropped Python 3.10 support: it removes the `StrEnum` compatibility shim, uses stdlib `tomllib`, and adds `portable-tempdirs` (which declares Python >=3.11).
- The Python 3.10 support removal was a deliberate breaking runtime change in 1.2.0; this 1.3.0 change is additive. Consumers must run Bridge under Python 3.11 or newer; no Python 3.10 compatibility guarantee remains.
- `portable-tempdirs` 0.1.2 is pinned to immutable Git commit `fd6dbd640630e6911a53b4d756089099ec870a8b`. VCS installation needs Git/network access or a prebuilt dependency artifact; the current direct-reference metadata is not suitable for PyPI upload without replacing the reference with a published, verified dependency and checking the resulting distribution metadata.
- The bridge uses the installed **Codex CLI**, not a direct OpenAI Responses API integration.
- Codex CLI features and app-server methods are checked using the installed CLI help, generated local schema and/or live protocol handshake. A matching version string alone is not authoritative.
- The app-server protocol remains experimental. Generated schema presence can mean “supported with limitations”; a successful matching RPC is stronger evidence.
- CLI model discovery does not confirm the account can invoke every listed model.

The local Codex CLI 0.160.1 help advertises `--ephemeral` on `codex exec` and
`--output-schema` on `codex exec resume`. The installed help defines flag
availability; the official [Codex exec command reference](https://learn.chatgpt.com/docs/developer-commands#codex-exec)
describes `--ephemeral` as disabling session rollout persistence and documents
`exec resume`. Bridge `ephemeral=False` omits the flag; the CLI's default
persistence behavior is not inferred from a bridge fake test. Resume schema
support is probed against the resume subcommand's own help.

## 1.3.0: per-exec opt-in web search

Bridge 1.3.0 introduces a backwards-compatible per-run native Codex web-search override for `CodexBridge.run()` and `start()`: `config_overrides={"web_search": "disabled"|"cached"|"indexed"|"live"}`. Set `config_policy="isolated"` for this override alone, or `explicit` for permitted config overrides. `project` rejects these overrides. The mode is passed to `codex exec` using `-c web_search=...`. Calls that omit `web_search` retain previous behavior and the installed CLI's effective defaults.

- This is **not** a guaranteed tool-use receipt or evidence that Codex visited a website. Bridge cannot currently attest search events or citations from the result.
- `CodexPermissions.network_access` is independent and does not configure Codex's hosted web-search tool.
- Existing `RunSecurityPolicy`/MCP isolation caveats remain. Enabling native search does not grant side-effect MCP, shell networking, filesystem write or execution permissions.
- Consumers pinned to **1.2.0** do **not** receive this option. Upgrade the pinned immutable commit only after CI, API compatibility review and a controlled test; coordinate all service-client/server versions in the deployment and preserve runtime state.
- Supported mode names follow the [Codex configuration basics](https://developers.openai.com/codex/config-basic). Actual availability depends on the installed Codex CLI/account; offline tests validate request/argument handling, not web access.

## Git repository check

`CodexBridge.run()` and managed `CodexBridge.start()` accept `skip_git_repo_check: bool = False`. When `True`, the bridge checks for `--skip-git-repo-check` in installed `codex exec --help` and raises `CapabilityUnavailableError` before execution/submission if absent. When `False`, existing CLI behavior is unchanged. This opt-in is not supported by `resume()`, `fork()`, `review()`, cross-process service-client submissions or the bridge CLI JSON contract.

For new exec runs, `ephemeral=True` remains the default and preflights that
`codex exec --help` advertises `--ephemeral` before including it; otherwise the
bridge raises `CapabilityUnavailableError`. `ephemeral=False` omits the flag.
To check that the public API includes this option without relying only on a
version string:

```python
from inspect import signature
from p4_codex_bridge import CodexBridge

supports_persistent_exec_option = "ephemeral" in signature(CodexBridge.run).parameters
cli_supports_ephemeral = CodexBridge().get_capabilities()["exec"]["ephemeral"]
```

The typed service `submit exec` request accepts the same boolean and the daemon
validates it again. On
`codex exec resume`, the bridge checks optional `--output-schema` and
`--output-last-message` against the resume-specific subcommand help rather than
assuming the base `exec` options apply.

### Coordinated bridge/client/service upgrades

Do not use a 1.2.0 `CodexServiceClient` against a still-running 1.1.0 service.
The 1.2.0 client serializes `ephemeral` (including its default `true`), while
the 1.1.0 service rejects unrecognized exec payload fields. The old service
fails the command explicitly; it does not provide 1.2.0 persistent-session
semantics. Stop the resident service, update the Python package in the service
environment, restart it, and verify `p4-codex service status --json` reports
the expected bridge version before submitting work. Use the same configured
state directory and preserve it during the upgrade.

A legacy exec payload that omits `ephemeral` is interpreted by the 1.2.0
service as `true`, which preserves the established ephemeral default. This
specific compatibility behavior does not establish general compatibility
between arbitrary client and service versions; keep them on the same release.

Check support without inference:

    codex --version
    codex exec --help
    python -m p4_codex_bridge capabilities

For the intended execution security policy and the distinction between discovery and effectiveness, see [security](SECURITY.md) and [capability matrix](CAPABILITY_MATRIX.md).

## Portable behavior

Windows supports module invocation and a `.cmd` wrapper; generated console-script `.exe` behavior depends on the environment. On Linux/macOS, use the current Python interpreter and installed CLI. See [installation](INSTALLATION.md) and [known limitations](KNOWN_LIMITATIONS.md).
