# P4-Codex-Bridge Python package

The importable `p4_codex_bridge` package provides the project's public Python API and operator CLI.

Import supported consumer contracts from the package root, for example `from p4_codex_bridge import CodexBridge`. The `client.py` facade, `service_client.py`, `cli.py`, runtime manager, worker, scheduler, registry and app-server modules implement the documented behaviors. Modules prefixed with `_` and internal persistence/process details are not stable consumer interfaces.

Use `python -m p4_codex_bridge --help` to inspect operator commands without a model call. See [Python API](../../docs/PYTHON_API.md), [architecture](../../docs/ARCHITECTURE.md), [security](../../docs/SECURITY.md) and [service](../../docs/SERVICE.md).
