# Runtime health and observability

## Human run discovery

`p4-codex ps` discovers recent/active exec and app-server runs from SQLite;
`inspect` resolves bridge or native IDs to a snapshot; `watch` is a read-only
poller that can be started by multiple terminals. Event journals are bounded
and sanitized. Historical replay is incomplete for event deltas that were not
persisted. See [LIVE_OBSERVABILITY.md](LIVE_OBSERVABILITY.md).

`CodexRuntimeManager.health()` returns machine-readable server liveness, protocol
version, registry accessibility, thread/turn counts, queue limits and capability
state. `get_metrics()` returns local counts for active threads/turns, completed
and failed turns, crashes, protocol errors and received events. Token usage and
duration aggregates are `null` until the runtime protocol provides a reliable
source; no estimates are substituted.

Internal logger name: `p4_codex_bridge.runtime`. Logs must not contain prompts,
environment dumps or authentication material. Error strings are redacted before
registry persistence. Event payloads are currently persisted as protocol data;
callers should not treat them as a secret vault or enable verbose external log
handlers without their own retention controls.

Health is local process/SQLite/protocol state, not proof that model inference,
authentication, MCP calls or a particular feature will succeed.

## Resident service views

`p4-codex service status` and `p4-codex health` read the latest sanitized
foreground-service heartbeat from the shared SQLite state directory.
`p4-codex metrics [--json]` returns recorded counters; token usage stays null
unless the manager observes it. The service snapshot includes SQLite database
size; cleanup counts are returned by each `maintenance clean` response and are
not retained as a historical metrics series. From another terminal, pass the same
`--state-dir` or set `P4_CODEX_BRIDGE_STATE_DIR`. These commands do not attach to
or drive a Codex turn. See [service](SERVICE.md).
