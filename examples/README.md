# Examples

This directory contains scripts demonstrating P4-Codex-Bridge behavior.

- [`scheduler_demo.py`](scheduler_demo.py) creates a **fake-only**, short-lived scheduler demonstration for inspecting queued jobs and resource limits. It does not run Codex or consume model tokens.

Run its help with `python examples/scheduler_demo.py --help`. For a demonstration, pass `--state-dir` to a disposable, explicitly chosen location. It creates scheduler SQLite state there; keep that state separate from production.

See [resource scheduler](../docs/RESOURCE_SCHEDULER.md) and [testing guidance](../docs/TEST_CATALOG.md).
