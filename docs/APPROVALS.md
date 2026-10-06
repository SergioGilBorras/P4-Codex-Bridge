# Approval handling

The protocol sends approval requests as server-initiated JSON-RPC requests, not ordinary notifications. Installed request methods are `item/commandExecution/requestApproval`, `item/fileChange/requestApproval`, and `item/permissions/requestApproval`. Fields and responses are versioned; consult [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md).

The bridge emits `ApprovalRequested` with a bridge approval id combining thread id, turn id, and the connection-local JSON-RPC request id. It includes only protocol fields, sanitized and size-limited. A turn enters `WAITING_APPROVAL` until resolution. `turn.pending_approval`, `bridge.status(turn_id)`, `p4-codex ps`, and `p4-codex approvals` expose the pending state.

Call `bridge.approve(id)` or `bridge.reject(id)`. Equivalent CLI commands write a local decision to the bridge SQLite registry; the owning live connection polls and returns the JSON-RPC response. An approval attached to a connection that has exited cannot be approved. Duplicate or unknown decisions fail.

Supported local handling policies:

- `MANUAL` (default): wait for an explicit caller decision.
- `AUTO_REJECT`: reject approval requests immediately.
- `NEVER_EXPECT_APPROVAL`: also reject if the protocol unexpectedly asks.
- `AUTO_APPROVE_SAFE_ONLY`: PLANNED. No deterministic safe-action classifier exists.

Approval timeout is separate from the turn iterator timeout and per-RPC response timeout. `approval_timeout_policy="reject"` (default) sends a controlled `decline`; `"error"` sends `cancel` to stop the requested action/turn and emits `ServerError` with code `APPROVAL_TIMEOUT`. It never silently approves. Permission-profile requests are rejected with `permissions: null`, matching the response's required `permissions` field. The bridge does not offer `acceptForSession`, exec-policy amendments, or persistent network-policy amendments through its current API.

`danger-full-access` requires an explicit `on-request` approval policy in the Bridge API. There is no default profile that combines full access with automatic approval. The installed protocol is experimental; upstream approval semantics may change between CLI versions.
