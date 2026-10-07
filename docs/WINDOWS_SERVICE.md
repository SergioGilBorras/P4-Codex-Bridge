# Windows service readiness

The supported operating mode today is a foreground process:

```powershell
p4-codex service run --config C:\P4\config\p4-codex.toml
```

It requires no stdin, prompt or implicit workspace cwd. Configure absolute
`state_dir`, `cwd` and `log_dir`; the service logs to a rotating file and stderr.
The process handles `Ctrl+C`, `Ctrl+Break` where Python exposes `SIGBREAK`, and
termination signals. Graceful stop goes through the SQLite control queue.

Supervisor choices (not installed or modified by this repository):

- **Task Scheduler** can start a fully qualified executable/script and supports
  local task query/run/end operations. Choose a user identity with access to the
  state directory and Codex ChatGPT login; configure restart-on-failure in the
  task settings. [Microsoft `schtasks` reference](https://learn.microsoft.com/en-us/windows/win32/taskschd/schtasks).
- **WinSW** wraps a process as a Windows Service and documents install/start/
  status/stop/restart commands. Pin and review the wrapper version/configuration
  before deployment. [WinSW project documentation](https://github.com/winsw/winsw).
- **NSSM** is another third-party service wrapper. Its service identity and child
  process monitoring behavior must be configured and validated by the operator.
  [NSSM project](https://git.nssm.cc/nssm/nssm).

The bridge has not implemented `ServiceBase`/SCM status callbacks, service
account installation, ACL management, or automatic wrapper installation. A
Windows wrapper must launch `p4-codex service run`, pass an explicit config path,
use a stable Python environment, and forward stop requests. The bridge's own
service `restart` is a new detached process; a supervisor should own automatic
process recovery and impose a restart limit/backoff.

Do not run the service as LocalSystem unless the Codex ChatGPT session and state
directory are intentionally provisioned for that account. No credentials are
copied between accounts.
