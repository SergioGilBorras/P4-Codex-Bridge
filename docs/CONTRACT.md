# Current Python execution contract (1.1.0)

The supported consumer boundary is the Python package-root `p4_codex_bridge` API and the documented `p4-codex` operator CLI. Internal scheduler, worker, SQLite schema and app-server transports are not stable public imports.

## Direct execution

    from p4_codex_bridge import (
        CodexBridge, CodexPermissions, SandboxMode, ApprovalPolicy,
    )

    bridge = CodexBridge(allowed_roots=[r"C:\work"])
    result = bridge.run(
        "Summarize the provided text",
        cwd=r"C:\work\scratch",  # must exist; can be empty
        profile="analysis",
        timeout_seconds=120,
        permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
        skip_git_repo_check=True,
        capture_last_message=True,
    )

This call may still be refused by `RunSecurityPolicy` if external MCP risk cannot be bounded or explicitly acknowledged. No filesystem sandbox alone guarantees that inherited MCP tools are read-only.

- `prompt`: nonempty text sent on stdin; not inserted into shell arguments.
- `cwd`: required absolute existing directory, validated against `allowed_roots` when provided.
- `model`: optional requested model identifier; availability is CLI/account-dependent.
- `profile`: `analysis` is the implemented named exec profile.
- `timeout_seconds`: validated positive bounded duration; the bridge supervises the child.
- `permissions`: typed sandbox/approval and optional validated additional roots/network settings.
- `config_policy`: `isolated`, `project`, or `explicit`; explicit config overrides are allowlisted and validated.
- `output_schema` and `capture_last_message`: use CLI-supported bridge-owned temporary files.
- `skip_git_repo_check: bool = False`: opt-in on `run()` and managed `start()` only. The CLI must advertise the option or the bridge fails before execution/submission.

The Codex process receives a shell-free argument vector. With the opt-in flag, the `exec` subcommand includes `--skip-git-repo-check` exactly once. `--json` emits events for normalized parsing; `-` reads prompt text through stdin.

## Managed execution

`CodexBridge.start()` returns `BridgeRun` and schedules an exec job in SQLite. Use `status()`/`watch()`/`inspect()` and `read_result()` to observe/consume it. This differs from synchronous `run()`, which bypasses the shared resource queue.

**Data retention:** A pending managed job stores a bounded prompt payload in the local SQLite scheduler until claimed or cancelled. Registry records retain sanitized run metadata; transient result files may hold redacted model output until consumed or cleaned. Do not assume all paths are non-persistent.

## Other operations

`resume()`, `fork()` and `review()` have separate typed exec contracts. Resumed/forked sessions inherit their stored permissions and require acknowledgement. The Git-check bypass option is **not** available on these operations, the typed service client, or JSON CLI submission.

Resident app-server operations are experimental and must be capability-gated at runtime. Their service and approval semantics are detailed separately.

## Results and failures

`RunResult` includes `ok`, `bridge_run_id`, `exit_code`, `content`, sanitized `stderr`, optional structured output, `error` and `duration_ms`. `RunResult.ok=False` is not a completed inference; inspect the structured error category/code when available.

Common worker error codes include `CODEX_NOT_FOUND`, `CODEX_AUTH_REQUIRED`, `CODEX_TIMEOUT`, `CODEX_EXIT_NONZERO`, `CODEX_EMPTY_RESPONSE` and `STRUCTURED_OUTPUT_INVALID`. Validation and capability failures can raise typed Python exceptions instead of returning a `RunResult`. CLI command exit behavior is documented in [CLI](CLI.md).

For exact signatures and experimental/stable method distinctions see [Python API](PYTHON_API.md). For risk boundaries see [security](SECURITY.md).
