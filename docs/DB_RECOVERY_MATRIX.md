# SQLite fault and recovery matrix

This matrix describes the local single-user state database. `RECOVERED` means
the bridge can continue without replaying uncertain work. It does not promise
hardware-level durability beyond SQLite and the host filesystem.

| Scenario | Classification | Behavior and evidence |
|---|---|---|
| Database absent | RECOVERED | Read-only health reports `DATABASE_ABSENT`; service startup creates the schema. |
| Current database | RECOVERED | `PRAGMA integrity_check`, known bridge schema version and additive `CREATE IF NOT EXISTS` checks. |
| Supported schema v1 | RECOVERED | Runtime manager migrates additively to v2 in one `BEGIN IMMEDIATE` transaction; existing thread/turn rows remain. |
| Migration interrupted | RECOVERED | SQLite rollback leaves the prior schema/version; retry is idempotent. Offline fault injection denies an `ALTER TABLE`, verifies rollback, then retries successfully. |
| Legacy initialization marker v3 | RECONCILED | A known marker from an earlier initialization path is normalized to v2 only after required columns/tables are present in the transaction. |
| Unknown schema version | FAIL_FAST / MANUAL_ACTION_REQUIRED | Startup refuses to mutate it; doctor reports `UNKNOWN_SCHEMA`. Back up and use a bridge version with a matching migration. |
| Corrupt database | UNHEALTHY / MANUAL_ACTION_REQUIRED | Read-only `database_health()` reports integrity/error status and does not alter the bytes. Stop the service, preserve a copy, then restore from a known backup; no automatic repair is attempted. |
| Database locked by another connection | DEGRADED | Schema initialization uses a bounded 2-second SQLite busy timeout and returns the SQLite lock error. Releasing the owner allows a clean retry; no schema change is committed. |
| Simulated disk-full/write failure | RECOVERED on retry; otherwise FAIL_FAST | DDL fault injection exercises transaction rollback. Physical disk exhaustion is not induced in tests; the write error is surfaced and startup does not claim success. Ensure free space and retry. |
| Stale SQLite transaction | RECOVERED | SQLite rolls back an uncommitted transaction when its connection closes; every bridge connection has deterministic close/rollback handling. |
| Stale process record | RECONCILED or UNKNOWN | Process creation identity and command fingerprint are checked. A mismatch is not controlled; uncertain work is retained as LOST/UNKNOWN, never re-executed. |
| Stale workspace lock | RECONCILED | In-flight work is conservatively marked LOST and its scheduler lock is released transactionally; queued payloads remain queued. |
| Stale scheduler claim | LOST / MANUAL_ACTION_REQUIRED | Claimed work is not redispatched after restart because the external side effect may have started. Inspect before resubmitting. |
| Stale approval | RECONCILED | Approval becomes `STALE_LOCAL`; recovery never approves or rejects it. Resolve through a new explicitly owned runtime if appropriate. |
| Partial runtime-command claim | FAILED / UNKNOWN | A `CLAIMED` command after service restart becomes FAILED with outcome unknown; it is not replayed. The idempotency key prevents a duplicate accepted submit. |
| Service crash during a write | RECOVERED or RECONCILED | Explicit transactions are atomic; claimed side effects with uncertain outcome are marked failed/unknown rather than replayed. |
| App-server crash during persistence | RECONCILED | A committed lifecycle record remains; an interrupted SQLite transaction rolls back. The turn is reconciled conservatively and is not rerun. |
| Maintenance dry-run/clean | RECOVERED | Synthetic tests verify only eligible resolved retention data is deleted. Active, queued, waiting, LOST/UNKNOWN work and pending approvals are preserved. |

## Atomicity and health scope

Runtime manager schema creation/migration, scheduler schema creation/migration,
service schema creation/migration, registry migration, and maintenance cleanup
use explicit SQLite transactions. The runtime schema version is published as
v2 only at the end of the transaction. Unknown versions fail closed. A failed
database connection is reported by health/doctor as unavailable/error; a
locked database is not treated as corruption.

`database_health()` is read-only. It reports integrity, bridge/SQLite schema
versions, migration status, stale record count, database size and pending
retention cleanup. Maintenance mutation is explicit via
`p4-codex maintenance clean`; `--dry-run` is the default-safe inspection path.

## Test evidence and limits

Offline coverage includes v1 migration, unknown-version refusal, interrupted
migration rollback/retry, a bounded locked-database failure/retry, corrupt DB
read-only detection, claim recovery and retention preservation. Actual disk-full,
power-loss, hardware/filesystem corruption and cross-user contention are not
simulated. Keep the state directory on a healthy local filesystem and maintain
operator backups.
