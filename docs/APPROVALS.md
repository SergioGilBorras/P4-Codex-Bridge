# Approval handling

The protocol sends approval requests as server-initiated JSON-RPC requests, not ordinary notifications. The bridge maps exactly `item/commandExecution/requestApproval`, `item/fileChange/requestApproval`, and `item/permissions/requestApproval`. A capability is fully runtime-confirmed only after each concrete request method has been observed; schema-only evidence remains limited. Fields and responses are versioned; consult [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md).

The one-turn connection and resident manager both emit `ApprovalRequested` with sanitized protocol details. The resident manager creates a stable `ap_...` id and binds it to `bridge_run_id`, `thread_id`, `turn_id`, and `server_id`. Its turn and scheduler status become `WAITING_APPROVAL`. `CodexRuntimeManager.list_pending_approvals()`, `get_approval(id)`, `approve(id)`, and `reject(id)` expose and resolve manager-owned requests. `p4-codex approvals`, `approve <id>`, and `reject <id>` use the shared local registry.

Call the matching manager or bridge API. CLI decisions update the SQLite record; the live reader that owns the original JSON-RPC request returns the response. The manager verifies `server_id` and in-memory request ownership before responding. A connection that exited cannot be approved, rejected, or reattached. Duplicate or unknown decisions fail.

Supported local handling policies:

- `MANUAL` (default): wait for an explicit caller decision.
- `AUTO_REJECT`: reject approval requests immediately.
- `NEVER_EXPECT_APPROVAL`: also reject if the protocol unexpectedly asks.
- `AUTO_APPROVE_SAFE_ONLY`: PLANNED. No deterministic safe-action classifier exists.

Approval timeout is separate from turn and JSON-RPC request timeouts. The one-turn API's default policy sends a controlled decline; the manager has `approval_timeout_seconds` (default 300) and also declines on expiry. It never silently approves. Permission-profile approval returns the exact requested permission object only after explicit approval, and `permissions: null` on rejection. After restart, local pending requests become `STALE_LOCAL` because the old JSON-RPC ID cannot safely be answered; recovery does not issue a decision. The bridge does not offer `acceptForSession`, exec-policy amendments, or persistent network-policy amendments through its current API.

`danger-full-access` requires an explicit `on-request` approval policy in the Bridge API. There is no default profile that combines full access with automatic approval. The installed protocol is experimental; upstream approval semantics may change between CLI versions.
