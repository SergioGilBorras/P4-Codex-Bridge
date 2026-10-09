# Tests and verification

The **ordinary automated suite is offline**: fake Codex CLI/app-server processes, SQLite fixtures, argument capture and local subprocesses. It does not send model prompts to the live Codex service. Do not promote a fake integration test to a claim that an account can run a particular model.

## Default commands

    python -m compileall -q p4_codex_bridge tests_py
    python -m unittest discover -s tests_py -v

Tests run with the intended Python interpreter. Windows launcher diagnostics requiring invocation of a potentially hanging packaging-generated `.exe` are opt-in and may be skipped by normal discovery.

## Current coverage map

| Source | Scope |
|---|---|
| `tests_py/test_bridge.py` | Direct/managed exec, `skip_git_repo_check` opt-in, capability gating, stdin safety, timeouts, outputs and process control |
| `tests_py/test_public_api.py` | Package-root export boundary and typed, closed public signatures |
| `tests_py/test_scheduler.py` | SQLite queue, limits, locks, managed dispatch and recovery |
| `tests_py/test_runtime_manager.py`, `test_app_server_events.py` | Experimental JSON-RPC manager, lifecycle, streams and approvals |
| `tests_py/test_security_and_capabilities.py` | Project trust, MCP risk, fail-closed policy and capability classification |
| `tests_py/test_service.py`, `test_service_client.py` | Foreground service, typed requests, same-user IPC and status |
| `tests_py/test_cli_contract.py`, `test_compatibility.py` | CLI protocol and compatibility diagnostics |
| `tests_py/test_windows_cmd_launcher.py`, `test_windows_launcher_install.py` | Supported wrapper, packaging and opt-in Windows launcher diagnostics |
| `tests_py/test_smoke_scripts.py` | Manual smoke script contracts without executing live model requests |

Automated results depend on the current commit and environment. Report actual passing, failing and skipped counts from a run; do not reuse old totals as present evidence.

## Manual verification

The scripts in `tests_real/` are **separate, opt-in** checks and some consume model usage. Examples include streaming, structured output, approval rejection, persistent threads, concurrency, service operation and AGENTS behavior. Do not include these scripts in a default CI/test loop or call them merely to inspect documentation.

For model-use safeguards see [test token budget](TEST_TOKEN_BUDGET.md); for unsupported behavior see [known limitations](KNOWN_LIMITATIONS.md).
