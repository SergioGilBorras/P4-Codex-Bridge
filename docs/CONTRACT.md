# Python execution contract

The public Python API is the only supported bridge interface for new integrations. This document preserves the former Node JSON contract as historical migration reference only; its JavaScript runtime and launcher were removed before 1.0.0 under [ADR-002](adr/ADR-002-python-only-runtime.md). The legacy contract below is not executable or supported by this package.

## Python input

```python
from p4_codex_bridge import CodexBridge, CodexPermissions, SandboxMode, ApprovalPolicy

bridge = CodexBridge(allowed_roots=[r"F:\ProyectosPYCHARM\PythonProject"])
result = bridge.run(
    "Analyze the selected code",
    cwd=r"F:\ProyectosPYCHARM\PythonProject\P4",
    profile="analysis",
    model=None,
    timeout_seconds=300,
    permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
)
```

`start()` accepts the same arguments and returns `BridgeRun`; use `read_result(run_id)` to consume the eventual result once. `run()` waits and consumes that result automatically.

## Installed Codex CLI mapping

Reference runtime: `codex-cli 0.160.1`, Node `v22.15.0`. The Python one-shot worker constructs this argument sequence with an array and `shell=False`:

```text
codex --ask-for-approval never exec --json --ephemeral --sandbox read-only -C <cwd> --ignore-user-config [--model <model>] [-c model_reasoning_effort=<effort>] [--output-schema <temporary-file>] -
```

`-` reads prompt text from stdin. `--json` emits JSONL; the bridge extracts `item.completed` with `agent_message`. `--output-schema` is used only if a schema is provided. `--output-last-message` is captured in a private bridge-owned temporary file. The Bridge also wraps the installed `exec resume`, `exec fork`, and `exec review` commands; resume/fork keep stored session policy and are separate from app-server thread resume/fork. Review targets are limited to `--uncommitted`, `--base`, or `--commit`. Verify flags after a Codex update. Sources: [Codex CLI docs](https://developers.openai.com/codex/cli/) and local `codex exec --help` plus subcommand help.

| Option | Rule / installed capability |
|---|---|
| `prompt` | Nonempty UTF-8 text; written to child stdin, never shell-interpolated or persisted. |
| `cwd` | Required absolute existing directory, canonicalized; checked against `allowed_roots` if set. |
| `profile` | `analysis` implemented. Other named profiles are explicitly planned and rejected. |
| `timeout_seconds` | Default 300, maximum 3600; timeout kills the managed process tree and records `TIMED_OUT`. |
| `model` | Optional model id passed as a separate CLI argument. `list_models()` discovers the current catalog. |
| `permissions` | Sandbox modes verified in `codex exec --help`; approval policy options are exposed in root `codex --help` and are placed before the `exec` subcommand. Defaults are read-only / never. Full access requires explicit `on-request`. |
| `reasoning_effort` | Passed as supported Codex config `model_reasoning_effort`; consult the selected model's advertised `supportedReasoningEfforts`. |
| `output_schema` | Optional JSON object, written to a short-lived schema file and passed using verified `--output-schema`; file is removed after execution. |
| `config_policy` | `isolated`, `project`, or `explicit`. User-only separation is unsupported by the installed CLI. |
| `config_overrides` | Only with `explicit`; keys and scalar values are validated and sent as individual `-c` arguments. |

## Python result

`run()` returns `RunResult`: `ok`, `bridge_run_id`, `exit_code`, final `content`, sanitized `stderr`, optional `structured_output`, normalized `error`, and `duration_ms`. `start()`/`list_runs()`/`status()` return process metadata without generated content. `read_result()` consumes and deletes the sanitized result file, if present.

Stable error codes presently emitted by the worker include `CODEX_NOT_FOUND`, `CODEX_AUTH_REQUIRED`, `CODEX_TIMEOUT`, `CODEX_OUTPUT_LIMIT`, `CODEX_EXIT_NONZERO`, `CODEX_EMPTY_RESPONSE`, `STRUCTURED_OUTPUT_INVALID`, and `CODEX_STOPPED`. Request validation raises `ValueError`; missing run IDs raise `KeyError`.

## Process lifecycle and exit codes

`p4-codex run` exits 0 only when Codex returned a final message successfully, 1 on a bridge/Codex error. `start`, `ps`, `status`, `stop`, `kill`, `models`, `version`, and `capabilities` emit JSON to stdout; operational errors emit sanitized JSON and a sanitized diagnostic to stderr.

Only PIDs recorded with creation identities in the bridge's SQLite registry can be stopped or killed. `stop` writes a bridge-owned stop request; the supervisor interrupts its Codex child and falls back to forced termination after the grace interval. `kill` terminates the registered Codex child and worker process tree immediately. Phase 1 does not claim resumable Codex sessions.

## Historical Node contract (not supported in 1.0)

The removed pre-1.0 JavaScript bridge accepted one JSON object on stdin and emitted one JSON response. Its fields and exit codes are recorded here for historical reference. There is no `bin/p4-codex-bridge.js` in this package; use the Python API or CLI. The legacy interface is not supported by 1.0.0.

## Credential and output handling

The child environment is allowlisted and omits API-key variables. The bridge never reads Codex auth files, tokens, cookies or the full environment. User-visible result text and stderr are redacted before writing the short-lived result file. That redaction reduces accidental disclosure; consumers must still handle generated text as sensitive data. Prompts, auth, and environment are not stored in the run database.
