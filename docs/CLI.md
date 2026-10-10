# CLI reference

The `p4-codex` entry point is installed by `pip install -e .`. Use the same
state directory/config path in each terminal; `--state-dir` can be supplied to
operator commands or set through `P4_CODEX_BRIDGE_STATE_DIR`.

The current command tree, output modes and exit-code table are in
[execution contract](CONTRACT.md). Every command leaf accepts `--json`; JSON
is also the default for commands with a finite result. `watch` and `events`
produce JSONL. Usage errors emit JSON with exit code 2. Root `--help` and
`--version` are informational text commands. `service run` is the foreground
exception and writes logs to stderr.

The `skip_git_repo_check` option is currently a Python
`CodexBridge.run()`/`start()` option only; it is not part of the CLI JSON or
service-client request contract.

## Resident service

```powershell
p4-codex service run --config C:\P4\config\p4-codex.toml
p4-codex service status --json --config C:\P4\config\p4-codex.toml
p4-codex health --json --config C:\P4\config\p4-codex.toml
p4-codex metrics --json --config C:\P4\config\p4-codex.toml
p4-codex service stop --config C:\P4\config\p4-codex.toml
p4-codex service restart --config C:\P4\config\p4-codex.toml
p4-codex service recover --config C:\P4\config\p4-codex.toml
```

`service run` is foreground and needs no stdin. `status`, `health`, `metrics`,
`ps`, `inspect`, `watch`, `resources`, `approvals`, and `cancel` use the local
registry/control database. Stop/restart/recover are requests through the
SQLite control channel. Finite service commands print sanitized JSON.

## Configuration and diagnostics

```powershell
p4-codex config validate --config C:\P4\config\p4-codex.toml
p4-codex config show --config C:\P4\config\p4-codex.toml
p4-codex doctor --config C:\P4\config\p4-codex.toml
p4-codex doctor --json --config C:\P4\config\p4-codex.toml
p4-codex maintenance status --json --config C:\P4\config\p4-codex.toml
p4-codex maintenance clean --dry-run --json --config C:\P4\config\p4-codex.toml
p4-codex --version
```

`doctor` runs local prerequisite probes (`codex --version`, login status, and
app-server help); it does not run inference. Its JSON report distinguishes the
module entry point, an installed `.cmd` shortcut and the optional console
script `.exe`. Doctor never executes the `.exe`. Windows users should use
`python -m p4_codex_bridge` or `Scripts\p4-codex.cmd`; see
[installation](INSTALLATION.md) and [known limitations](KNOWN_LIMITATIONS.md).
See [configuration](CONFIGURATION.md) for precedence and validation.

Maintenance status always previews. Maintenance clean mutates SQLite unless
`--dry-run` is supplied. Active, queued, waiting, LOST, unknown and pending
approval records are retained. `doctor --json` emits machine-readable checks.

## Resource and run inspection

```powershell
p4-codex ps --active
p4-codex ps --task P4-123 --json
p4-codex inspect br_...
p4-codex watch br_... --follow --no-deltas
p4-codex resources
p4-codex cancel br_...
p4-codex approvals
```

These commands can observe/control runs in the shared local registry. Typed
cross-process submission is available through `submit exec`, `thread create`
and `turn start`; the daemon revalidates each payload before dispatch. `watch`
is read-only; `cancel` is an explicit state-changing operation.

Every finite command writes JSON by default; `--json` is accepted consistently
on command leaves. Errors return a sanitized JSON object on stdout with a
nonzero exit code; diagnostics go to stderr. `service run` writes operational
logs to stderr while state is queryable through other commands.

## Fake-only service demo

For a second-terminal operator walkthrough without Codex or model calls:

```powershell
p4-codex service run --fake --state-dir "$env:TEMP\p4-codex-demo"
# second terminal
p4-codex service demo --state-dir "$env:TEMP\p4-codex-demo"
```

The `--fake` option is hidden from normal help and is intended for development
verification only. The demo is rejected unless the running service reports the
fake protocol identity.
# Cross-process submissions

While `p4-codex service run` is active, submit JSON requests from another
process. Example:

```powershell
'{"prompt":"Reply exactly: OK","cwd":"F:/safe/workspace","profile":"analysis"}' |
  p4-codex submit exec --state-dir "$env:LOCALAPPDATA/p4-codex-bridge" --wait 30 --json
```

For managed `codex exec` persistence, include `"ephemeral": false` in the
`submit exec` JSON. It is strictly validated and defaults to `true`. The
submission ack contains the bridge run ID; after Codex completes, use
`p4-codex inspect <bridge_run_id>` to read the native session ID and continue
it through `CodexBridge.resume()` with explicit permission confirmation.
This is distinct from app-server persistent threads.

Create a persistent app-server thread by piping `cwd`, `profile`, optional `model`,
`sandbox`, `approval_policy`, `config_policy`, and `metadata` to
`p4-codex thread create`. Start a turn by piping `thread_id`, `prompt`, and
optional `timeout_seconds`, `metadata`, `access_mode`, and `resource_priority`
to `p4-codex turn start`. The commands return JSON on stdout and never start a
service implicitly. `--wait` bounds how long the CLI waits for command ack; a
timed-out waiter may submit again using the same JSON `idempotency_key`.
