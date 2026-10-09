# P4-Codex-Bridge

P4-Codex-Bridge is a Python interface and operator CLI for the locally installed OpenAI Codex CLI. It uses the user's existing Codex authentication and provides execution controls, lifecycle tracking, observability, and experimental app-server integrations.

**Current source version: 1.1.0.** This repository is a Python implementation; no Node.js bridge runtime or JavaScript API is provided. Node.js may still be required by a particular Codex CLI installation.

## What works today

- Synchronous `CodexBridge.run()` and managed queued `CodexBridge.start()` execute `codex exec`. Prompts are passed on stdin, never interpolated into a shell command.
- `skip_git_repo_check=True` is supported by `run()` and `start()` for existing non-Git directories when the installed CLI advertises `--skip-git-repo-check`. Default: `False`.
- `cwd` validation, optional `allowed_roots`, sandbox/approval settings, timeouts, model options, structured output, final-message capture and safe result handling.
- A shared SQLite scheduler for managed exec jobs and resident app-server turns, with resource limits, workspace locks, cancellation and local run discovery. Direct `run()` calls do not use the scheduler.
- A resident app-server manager for threads, turns, normalized events, manual approvals and conservative lifecycle recovery. Its protocol is experimental and capability-gated.
- A Python operator CLI (`p4-codex` or `python -m p4_codex_bridge`), a foreground local service, and typed cross-process service requests.
- Local capability discovery, safe diagnostics, and fake/offline automated tests.

**Limitations:** Per-run MCP/tool isolation is not guaranteed; project configuration and external MCP side effects require explicit risk assessment. App-server and child-visible tools/skills must not be inferred from host session inventories. See [security](docs/SECURITY.md), [capabilities](docs/CAPABILITY_MATRIX.md) and [known limitations](docs/KNOWN_LIMITATIONS.md).

## Requirements

- Python 3.10+.
- An installed Codex CLI and authentication through its supported login mechanism.
- A real, existing `cwd` for Codex calls; creating a new directory or a Git repository is not a bridge requirement.
- Installation into a selected Python environment. The bridge does not require `OPENAI_API_KEY` and does not perform a direct Responses API call.

## Install from this checkout

From the repository root:

    python -m pip install -e .
    python -m p4_codex_bridge --version
    codex --version
    codex login status

For Windows, prefer `python -m p4_codex_bridge` or the installed `p4-codex.cmd` entry point when the generated console-script executable is unreliable. See [installation](docs/INSTALLATION.md).

## Python API example

The example illustrates the API, not a guarantee that an untrusted project or an unknown external MCP configuration can pass the security gate.

    from p4_codex_bridge import (
        CodexBridge, CodexPermissions, SandboxMode, ApprovalPolicy
    )

    root = r"C:\work\scratch"  # existing directory
    bridge = CodexBridge(allowed_roots=[root])
    result = bridge.run(
        "Describe the input in one sentence",
        cwd=root,
        permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
        skip_git_repo_check=True,  # explicit opt-in for non-Git cwd
        capture_last_message=True,
    )
    print(result.content if result.ok else result.error)

`skip_git_repo_check` only bypasses the CLI Git-context check; it does **not** change sandbox, filesystem read visibility, allowed roots, approvals, MCP configuration, or Codex authentication. `CodexBridge.resume()`, `fork()`, `review()` and service-client/CLI submissions have separate contracts.

## Operator CLI

    python -m p4_codex_bridge --help
    python -m p4_codex_bridge capabilities
    python -m p4_codex_bridge models
    python -m p4_codex_bridge ps
    python -m p4_codex_bridge doctor --json

Consult [CLI](docs/CLI.md) before submitting jobs. The foreground service and cross-process submission have their own [service documentation](docs/SERVICE.md). Capabilities and model access depend on the installed Codex version and account, not merely on the bridge package version.

## Verification

    python -m compileall -q p4_codex_bridge tests_py
    python -m unittest discover -s tests_py -v

Automated tests use fake Codex/app-server processes and do not make real model calls. Scripts in `tests_real/` are manual, opt-in and may incur usage.

## Documentation

Start with the [documentation index](docs/README.md) for current API, architecture, security, operational guidance, known limitations and the [roadmap](docs/ROADMAP.md).
