# P4-Codex-Bridge 1.1 API evolution

This addendum records the backward-compatible API change from the frozen
1.0.0 contract. [`CONTRACT_1_0.md`](CONTRACT_1_0.md) remains the historical
1.0.0 contract and is not edited by this addition.

## Version

The development package version is `1.1.0`, sourced from
`p4_codex_bridge.__version__`. This source change does not publish a package or
create an official release.

## `CodexBridge.run()` and `CodexBridge.start()`

Both methods add this keyword-only argument after `output_schema`:

```python
skip_git_repo_check: bool = False
```

Only an actual `bool` is accepted. The default `False` leaves the `codex exec`
argument vector unchanged and does not require the installed CLI to support the
option. When `True`, the bridge first checks `codex exec --help` for the exact
`--skip-git-repo-check` option. Missing capability raises
`CapabilityUnavailableError` before a direct process starts or a managed run is
submitted. A supported CLI receives the flag exactly once as an argument after
the `exec` subcommand. The prompt remains on stdin and subprocess invocation
continues to use an argument array with `shell=False`.

`get_capabilities()["exec"]["skip_git_repo_check"]` reports the discovered
boolean; `get_capabilities()["exec"]["skip_git_repo_check_capability"]`
reports the status and discovery source. Capability is checked from installed
CLI help, not guessed from a version number.

## Scope and security

The option applies only to `run()` (direct one-shot exec) and `start()`
(managed/scheduled exec). `resume`, `fork`, `review`, `CodexServiceClient`, and
the service submit/CLI payloads do not accept it. Their contracts and request
models are unchanged.

The flag only skips Codex's repository-context check. It does not disable the
Codex sandbox or bypass bridge cwd and `allowed_roots` validation,
`RunSecurityPolicy`, permissions, approval policy, authentication, or MCP
security gates. It is opt-in and defaults off. `cwd` remains an existing
directory required by bridge path policy; a Git repository is not required
when this option is enabled.

Example:

```python
result = bridge.run(
    "Inspect this workspace",
    cwd=r"C:\P4\existing-directory-without-git",
    skip_git_repo_check=True,
)
```

No artificial repository or new directory is created. See
[`PYTHON_API.md`](PYTHON_API.md) for compatibility and examples.
