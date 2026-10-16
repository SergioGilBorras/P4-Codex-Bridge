# Optional real-Codex smoke tests

The `smoke_*.py` scripts are **not** part of automated unit-test discovery. Some start authenticated Codex processes, can consume inference/web-search usage and may have external tool effects. They require separate operator authorization; scripts that launch model turns use an explicit `--run-real-turn` acknowledgement.

Use `python tests/manual/<script>.py --help` to inspect the individual contract without inference. Do not run these scripts in CI or as part of cleanup.

`context_workspace/` and `approval_workspace/` hold harmless checked-in smoke fixtures. `smoke_workspace/` holds a harmless README and is a workspace for manually authorized checks. Runtime outputs and private state must remain ignored.

See [test catalog](../../docs/TEST_CATALOG.md) and [model-use policy](../../docs/TEST_TOKEN_BUDGET.md).
