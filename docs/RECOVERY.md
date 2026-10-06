# Runtime recovery

`CodexRuntimeManager` owns one stdio `codex app-server` child, identified in its
registry by bridge instance ID, PID, command fingerprint and start time. The OS
lock is advisory and released by the OS after owner exit; PID metadata alone is
never used to terminate another process. Only the direct `Popen` child is stopped.

Threads are persistent (`ephemeral: false`) and can later be resumed through the
official `thread/resume` protocol method, but automatic reconciliation/resume is
not yet implemented. A turn interrupted by manager/server loss is `UNKNOWN`;
`recover(dry_run=True)` reports this and `recover(dry_run=False)` records it.
Turns are never replayed automatically. Exec child re-adoption is not supported.

SQLite schema version 1 adds server, thread, turn and lifecycle-event tables.
Unknown schema versions fail closed. Lifecycle events are stored; streaming text
deltas remain in memory. Replay of all message deltas is not promised.

The current runtime owns a single local manager lock and a single app-server
reader. Cross-process remote control/reconnection and Windows daemon/proxy mode
are not established by the installed interface.
