# Version compatibility

| Codex CLI | Local observations | Runtime status |
|---|---|---|
| 0.160.0 (audit baseline) | app-server experimental; generated local v2 schema includes `thread/start`, `thread/resume`, `thread/turns/list`, `turn/start`, `turn/interrupt`; daemon/proxy help is platform-oriented and proxy documents a socket path | Historical audit baseline; bridge support is tracked in the capability matrix |
| 0.160.1 (current local check, 2026-10-06) | `codex --version`, CLI help and generated local app-server schema checked; app-server remains experimental | Runtime manager uses `thread/start` and `turn/start`; app-server thread recovery/resume is not exposed by the bridge |

The bridge records the server's `initialize` protocol version and `serverInfo`.
It does not infer support for a method from a version string. Capability gates
must use the local CLI/schema or a successful protocol handshake; a method-not-
found response remains authoritative for that operation. The generated schema
is version-specific and app-server is experimental, so validate after Codex
upgrades. No minimum/maximum compatibility range is asserted yet.

OpenAI Developer Docs MCP was not callable in this implementation turn. The
installed CLI/schema was the primary source of truth. Session MCP visibility is
not evidence of child-process visibility.
