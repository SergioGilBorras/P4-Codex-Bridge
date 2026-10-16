# Runtime and consumer compatibility

## Supported environment

- **P4-Codex-Bridge 1.4.1** source; no package release is claimed.
- Python **3.11+**. Python 3.10 or older is unsupported.
- `portable-tempdirs 0.1.2`, installed from its pinned Git commit `fd6dbd640630e6911a53b4d756089099ec870a8b`; installation requires access to the source or an approved offline artifact.
- Official Codex CLI installed and authenticated for the current operating-system user. Model availability, `codex exec` flags and app-server RPCs depend on the **installed** CLI and the account; they are not guaranteed by the Bridge version.
- Native Codex interface, not a direct OpenAI Responses API integration.

## Exec capabilities

`CodexBridge.run()` and `start()` support `ephemeral=True` by default. `ephemeral=False` omits `--ephemeral`, and the result is resumable only if Codex emits a valid session ID. `skip_git_repo_check=True` is available for those operations when `codex exec --help` advertises the corresponding flag.

The **per-execution web-search configuration** accepts `disabled`, `cached`, `indexed` or `live`. With `config_policy="isolated"`, `web_search` must be the **only** config override; `config_policy="explicit"` permits other validated overrides. `project` rejects overrides. Bridge forwards the mode through `-c web_search=...` without enabling OS shell network access or per-run MCP permissions.

**A requested mode is not evidence of a search.** Opted-in `web_observations` and `web_receipts` report bounded native events and selected validated public documentation page URLs, but cannot prove successful page loading, page contents or citation correctness. Consumers needing third-party code must corroborate sources and require their own approval gates. A typed `RunSecurityPolicy` and read-only sandbox are not proof of MCP isolation.

## Checking a concrete installation

```powershell
python -m p4_codex_bridge --version
python -m p4_codex_bridge --help
python -m p4_codex_bridge capabilities
codex --version
codex exec --help
codex login status
```

The effective model entitlement is not established by listing models. For source/environment compatibility, run `python -m unittest discover -s tests_py -v` without inference.

## Updating a resident service

The Python client and foreground service must use the **same installed Bridge version**. Stop the service, update the Python package without deleting its state directory, restart, and verify `p4-codex service status --json` before submission. Unknown or incompatible typed payloads are rejected rather than silently reinterpreted. The format of stored state and support for active turn recovery depend on explicit lifecycle checks.

Current boundaries are described in [security](SECURITY.md), [Python API](PYTHON_API.md), [service](SERVICE.md), and [known limitations](KNOWN_LIMITATIONS.md). Page-content attestations and independently corroborated web evidence are not supported; candidate improvements are listed in the roadmap.
