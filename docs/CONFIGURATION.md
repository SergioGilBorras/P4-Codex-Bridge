# Service configuration

The service accepts TOML. Start from [`p4-codex.example.toml`](../p4-codex.example.toml)
and save a private copy outside the repository. It contains no secrets.

```powershell
p4-codex config validate --config C:\P4\config\p4-codex.toml
p4-codex config show --config C:\P4\config\p4-codex.toml
p4-codex doctor --config C:\P4\config\p4-codex.toml
```

Precedence is explicit CLI value, supported environment override, TOML value,
then default. Unknown sections and keys fail validation. There is currently no
`config_version` field; unknown fields fail fast rather than being ignored.
Currently the service CLI can override config path and state
directory; `P4_CODEX_BRIDGE_CONFIG` selects a config file, and
`P4_CODEX_BRIDGE_STATE_DIR` overrides TOML state directory.
`P4_CODEX_BRIDGE_CODEX_EXECUTABLE` overrides `[codex].executable` and normal
Codex discovery. Other values come from TOML/defaults;
unsupported environment aliases are not silently recognized.

Unknown sections/keys, nonabsolute state/workspace/log paths, nonexistent cwd,
invalid timeout/shutdown/logging values, and unsupported shell-shim executable
paths fail validation before the app-server starts. `config show` emits resolved
paths and effective limits but no environment or authentication material.
Environment variables in TOML paths use Windows `%NAME%` / platform-native
expansion.

The 1.0 configuration has no `config_version` key. TOML is a single strict
schema: unknown sections/keys fail closed. A future incompatible schema change
must provide an explicit migration or a separately named config format; it
must not silently reinterpret existing fields. Config may select an executable
but cannot store API keys, bearer tokens, passwords, cookies, or auth headers.

Supported bridge environment variables are exactly:

| Name | Meaning | Precedence |
|---|---|---|
| `P4_CODEX_BRIDGE_CONFIG` | Default TOML path when `--config` is absent | CLI > env > no file |
| `P4_CODEX_BRIDGE_STATE_DIR` | State directory override | CLI > env > TOML > platform default |
| `P4_CODEX_BRIDGE_CODEX_EXECUTABLE` | Native Codex executable override | env > `[codex].executable` > discovery |

Other service fields are configured only through their named TOML keys. Runtime
limits and profile limits use the exact `RuntimeLimits` names in
`p4-codex.example.toml`; `[security]` and per-run MCP filter fields are not
accepted because the CLI does not expose verified per-run MCP isolation.

Frozen TOML keys:

| Table | Keys |
|---|---|
| `[service]` | `state_dir`, `cwd`, `startup_timeout_seconds`, `shutdown_timeout_seconds`, `shutdown_policy`, `approval_timeout_seconds` |
| `[runtime]` | `global_max_active`, `app_server_max_active`, `exec_max_active`, `max_active_threads`, `max_queue_size`, `profile_limits` |
| `[logging]` | `log_dir`, `max_bytes`, `backup_count`, `format` (`human` or `json`) |
| `[codex]` | `executable`, `allowed_roots` |
| `[retention]` | `days`, `max_completed_runs`, `max_events_per_run` |

Per-run risk settings are a typed `RunSecurityPolicy` in Python/service request
payloads; they are not a service-wide TOML table. Unknown keys are errors.

The example state directory resolves under `%LOCALAPPDATA%`. The service does
not modify NTFS ACLs; deploy it under a per-user local directory whose inherited
ACLs are appropriate. SQLite on network shares is not a supported coordination
backend. `[retention]` supports `days`, `max_completed_runs`, and
`max_events_per_run`; it is applied only by explicit `maintenance clean`, never
automatically at service startup.
