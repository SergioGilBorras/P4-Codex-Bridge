# P4-Codex-Bridge

P4-Codex-Bridge is the shared Python API and compatibility CLI for invoking the official Codex CLI using the user's already authenticated Codex/ChatGPT session. Planned consumers are P4-Planning-Agent, P4-Jira-Agent-Orchestrator, and `F:\ProyectosPYCHARM\PythonProject\GestorProyectosIA`. No consumers are integrated or modified in this phase.

The bridge owns Codex invocation, process lifecycle, cwd, timeout, sandbox/approval flags, stdin/stdout, parsing, temporary files, secret redaction and normalized errors. It does not own Jira, scheduling, planning, requirements, P4 pipelines or Orchestrator task persistence.

## Requirements and authentication

- Python 3.10 or newer and Codex CLI installed.
- Node.js is still required by the currently installed Codex CLI `0.160.1` runtime on this machine.
- Sign in using the official Codex ChatGPT login (`codex login`); the bridge delegates authentication to that installation.
- `OPENAI_API_KEY` is not required. The bridge does not call the Responses API, read Codex tokens/cookies, or pass API key environment variables to child processes.
- Phase 1 uses only Python's standard library. The official Python SDK `openai-codex` exists but is not installed here; see [architecture](docs/ARCHITECTURE.md).

## Python usage

Install this checkout in the consumer environment:

```powershell
python -m pip install -e .
```

```python
from p4_codex_bridge import CodexBridge, CodexPermissions, SandboxMode, ApprovalPolicy

bridge = CodexBridge(allowed_roots=[r"F:\ProyectosPYCHARM\PythonProject"])
result = bridge.run(
    "Analyze the selected project",
    cwd=r"F:\ProyectosPYCHARM\PythonProject\P4",
    profile="analysis",
    timeout_seconds=300,
    permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
)
if result.ok:
    print(result.content)
else:
    print(result.error)
```

For an existing directory outside a Git repository, opt in to Codex's
repository-context bypass without changing the workspace or sandbox:

```python
result = bridge.run(
    "Summarize these files",
    cwd=r"C:\P4\scratch",
    skip_git_repo_check=True,
)
```

`cwd` must still be an existing directory inside `allowed_roots`. The option is
available on `run()` and managed `start()` when the installed Codex CLI advertises
`--skip-git-repo-check`; check
`bridge.get_capabilities()["exec"]["skip_git_repo_check"]` before relying on it.
It does not disable the sandbox. See [Python API](docs/PYTHON_API.md) for empty,
temporary and existing non-Git workspace examples and compatibility boundaries.

`CodexBridge.start()` is for asynchronous process management; it starts a managed Codex CLI operation. `run()` also supports `resume()`, `fork()` and `review()`; resume/fork retain the stored Codex session permissions and explicitly require caller acknowledgement. `output_schema` returns parsed `structured_output`; `capture_last_message=True` hides the CLI temp-file handling. See [Python API](docs/PYTHON_API.md) and [lifecycle](docs/LIFECYCLE.md).

For live app-server streaming, use `CodexBridge.start_turn()` or `stream_events()` / `astream_events()`. It returns normalized message, tool and lifecycle events; approval requests are manual by default and can be explicitly approved or rejected while the owning turn is live. This API keeps its existing per-turn connection behavior. See [events](docs/EVENTS.md), [approvals](docs/APPROVALS.md), and the [capability matrix](docs/CAPABILITY_MATRIX.md).

The Phase 5 `CodexRuntimeManager` owns one resident stdio app-server process and a SQLite lifecycle/resource queue. Managed `CodexBridge.start()` exec jobs use that same queue, global/backend limits and workspace locks; direct one-shot `run()` stays unscheduled. Active cancellation is routed through the owning backend. Claimed exec work is not re-adopted after controller loss, and claimed app-server turns are not replayed automatically. See [runtime recovery](docs/RECOVERY.md), [resource scheduler](docs/RESOURCE_SCHEDULER.md), and [version compatibility](docs/VERSION_COMPATIBILITY.md).

Live discovery is available with `p4-codex ps`, `p4-codex inspect <id>`, and read-only `p4-codex watch <id> --follow`. Pass optional operational metadata (`agent_name`, `agent_role`, `task_key`, `project`, `workspace`) through Python `start()` / `run()` or manager thread/turn creation. See [live observability](docs/LIVE_OBSERVABILITY.md). Attach is not supported.

## Operator CLI

The installed Python script is `p4-codex`. For local checkout use `python -m p4_codex_bridge`.

```powershell
'{"prompt":"Summarize this project","cwd":"F:\\ProyectosPYCHARM\\PythonProject\\P4","profile":"analysis"}' | python -m p4_codex_bridge run
python -m p4_codex_bridge ps
python -m p4_codex_bridge status <run-id>
python -m p4_codex_bridge result <run-id>
python -m p4_codex_bridge models
python -m p4_codex_bridge capabilities
python -m p4_codex_bridge events <turn-id>
python -m p4_codex_bridge events <turn-id> --follow --json
python -m p4_codex_bridge approvals
python -m p4_codex_bridge approve <approval-id>
python -m p4_codex_bridge reject <approval-id>
python -m p4_codex_bridge service run --config C:\P4\config\p4-codex.toml
python -m p4_codex_bridge service status --config C:\P4\config\p4-codex.toml
python -m p4_codex_bridge health --config C:\P4\config\p4-codex.toml
python -m p4_codex_bridge metrics --json --config C:\P4\config\p4-codex.toml
python -m p4_codex_bridge service stop --config C:\P4\config\p4-codex.toml
```

Commands also include `service run|status|stop|restart|recover`, `health`, `metrics`, `config show|validate` and `doctor`. `service run` needs no stdin. Pass the same `--state-dir` (or environment override) from other terminals so their discovery/control commands use the daemon's database. `run` and `start` receive one JSON object on stdin. stdout is JSON for one-shot CLI results; diagnostics are sanitized on stderr. `events --follow` polls lifecycle events only; it cannot recover message deltas. `cancel` withdraws queued work or asks the owning backend to interrupt active managed work. See [CLI](docs/CLI.md), [service](docs/SERVICE.md), [configuration](docs/CONFIGURATION.md), [installation](docs/INSTALLATION.md), and [Windows guidance](docs/WINDOWS_SERVICE.md).

## State and scope

Phases 1–3 provide one-shot exec, dynamic model discovery, managed process registry, ephemeral app-server streaming, event normalization, explicit approvals, interruption, bounded queues and lifecycle replay. Phase 4 adds exec resume/fork/review, structured output, final-message capture, typed tuning/permissions, config introspection and diagnostic MCP/skills discovery. These diagnostic app-server views do not prove a separate exec child sees the same resources. Child visibility/effectiveness for AGENTS, skills and MCPs remains unconfirmed until the manual checks are run. Process rows include bridge run id, PIDs, backend, cwd, model, profile, timestamps, status, exit code and sanitized last error. Exec registry rows omit prompts. Pending scheduler payloads are persisted in SQLite until claim/cancel (maximum 1 MiB), then deleted. Lifecycle events/approval state are sanitized; message deltas/tool output are transient.

Python is the only canonical runtime. The old independent JavaScript implementation and npm workflow were removed: there was no bridge consumer requiring them, and they duplicated subprocess/config/security logic. The legacy JavaScript sources in P4-Planning-Agent were not modified. `CodexBridge.resume/fork/review` are exec operations; persistent app-server thread resume/fork are separate manager operations.

## Tests

```powershell
python -m compileall -q p4_codex_bridge tests_py
python -m unittest discover -s tests_py -v
python tests_real/smoke_streaming.py
```

Manual smokes are not part of the automated suite: `python tests_real/smoke_structured_output.py`, `python tests_real/smoke_agents_context.py --policy project` (also accepts `isolated` or `explicit`), and `python tests_real/smoke_mcp_visibility.py`. Each generation smoke makes at most one turn. MCP visibility only queries the diagnostic app-server inventory.

Automated tests use fake Codex/app-server executables; they do not call Codex or Jira. Manual real smokes are separate: `python tests_real/smoke_streaming.py` makes one read-only turn; `python tests_real/smoke_approval_reject.py` is manual only and rejects a file-write request in its isolated workspace. There is no Node/npm test workflow.

## Documentation

- [Architecture and capability audit](docs/ARCHITECTURE.md)
- [Installation](docs/INSTALLATION.md) and [known limitations](docs/KNOWN_LIMITATIONS.md)
- [Python API](docs/PYTHON_API.md)
- [Process lifecycle and Phase 2](docs/LIFECYCLE.md)
- [Installed protocol capability matrix](docs/CAPABILITY_MATRIX.md)
- [Streaming events](docs/EVENTS.md)
- [Approvals](docs/APPROVALS.md)
- [Execution contract](docs/CONTRACT.md)
- [Profiles](docs/PROFILES.md)
- [Features](docs/FEATURE_CATALOG.md)
- [Tests](docs/TEST_CATALOG.md)
- [Test token budget](docs/TEST_TOKEN_BUDGET.md)
- [Tools](docs/TOOLS_CATALOG.md)
- [Skills](docs/SKILLS_CATALOG.md)
# Resource scheduling

The resident app-server runtime and managed `CodexBridge.start()` exec runs share a persistent SQLite resource queue, global/backend/profile limits, workspace locks, cancellation and run observability. Direct one-shot `CodexBridge.run()` remains outside scheduling. P4-Jira-Agent-Orchestrator continues to select and prioritize business work; the bridge schedules only Codex resources. See [Resource Scheduler](docs/RESOURCE_SCHEDULER.md) and [Concurrency](docs/CONCURRENCY.md). `p4-codex resources` and `p4-codex limits` inspect local capacity. Automated scheduler tests use fakes and consume no Codex tokens.
