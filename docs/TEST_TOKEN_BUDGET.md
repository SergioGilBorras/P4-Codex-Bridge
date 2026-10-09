# Model-use policy for tests

## Default: no real inference

The automatic `unittest` suite is deliberately **zero-inference**. It uses fake CLI/app-server processes and local SQLite fixtures; it must not call Codex models or external side-effecting MCPs.

    python -m unittest discover -s tests_py -v

Syntax compilation, packaging checks, local CLI help and documented fake-service tests do not themselves require model generation.

## Opt-in manual checks

Scripts under `tests_real/` may contact the authenticated Codex service. Run them only with explicit, separate authorization, a known workspace/security policy and a recorded call budget.

Before manual execution:

1. Identify the exact script and its expected maximum number of turns. Inspect the source instead of guessing.
2. Check auth, CLI and supported flags without inference.
3. Assess `RunSecurityPolicy` and inherited MCP risks; `READ_ONLY` does not block external tool actions.
4. Use an isolated, authorized `cwd` and the minimum data necessary.
5. Capture run IDs, status, requested/effective model where exposed, usage when available, and the final structured error on failure.
6. Do not automatically retry after timeout or an ambiguous process failure.

**Unknown usage is not zero usage.** Model listings do not prove entitlement, and a missing successful response does not prove that the model was never contacted.

See [security](SECURITY.md) and [test catalog](TEST_CATALOG.md).
