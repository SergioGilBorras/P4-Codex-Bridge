# Known limitations

These are current **limitations**, not a history of investigations.

- **External MCPs:** Filesystem `READ_ONLY` does not restrict external side-effecting MCP tools. The bridge cannot guarantee a per-run MCP/tool allowlist or prove that a diagnostic tool inventory applies to another exec child. See [security](SECURITY.md).
- **App-server:** JSON-RPC support is experimental and capability-gated. Active turns cannot be blindly adopted after a manager restart; persisted lifecycle events do not include complete message-delta replay.
- **Managed execution:** Direct `run()` is outside the resource scheduler. Managed claimed jobs are not automatically replayed after uncertain failures, to avoid duplicate work.
- **Persistent `codex exec` sessions:** `ephemeral=False` omits Codex's `--ephemeral` flag and requires a native session ID in the result. Fake tests verify the command/result contract only; no live inference in this change proves persistence or resume. The caller must retain Codex session data and the workspace. Resume does not guarantee changing the session's stored workspace.
- **Capabilities and models:** Installed CLI help, generated schema and model lists cannot prove login entitlement or a later run's exact available tools.
- **Windows launcher:** Use `python -m p4_codex_bridge` or the installed `p4-codex.cmd` wrapper. Some environments may hang when invoking the packaging-generated `p4-codex.exe`; that executable is optional and its reliability is not guaranteed. `doctor` does not automatically invoke a potentially hanging launcher.
- **Windows SCM integration:** A foreground local service is available, but no native Windows SCM wrapper is included.
- **Git context:** `skip_git_repo_check` is supported only for Python `run()`/`start()`, requires an advertised CLI flag, and does not change the sandbox or allowed roots.
- **Result redaction:** Redaction reduces accidental exposure but is not a data-loss prevention guarantee; downstream applications remain responsible for handling sensitive generated content.

See [roadmap](ROADMAP.md) for candidate improvements.
