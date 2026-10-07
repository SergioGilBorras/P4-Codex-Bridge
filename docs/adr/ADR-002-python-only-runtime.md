# ADR-002: Python-only canonical runtime

- **Status:** Accepted
- **Date:** 2026-10-07

## Decision

Python is the only canonical P4-Codex-Bridge implementation and public runtime.
The independent JavaScript source, JS CLI, `package.json`, npm workflow and JS
tests are removed from this repository. The public API is Python, with the
Python CLI as the process boundary for automation.

## Context

There is no integrated consumer in this repository that requires the JS
implementation. It duplicated Codex subprocess, configuration, permission and
redaction behavior instead of delegating to Python, creating two security and
compatibility surfaces to maintain. The legacy files under
`P4-Planning-Agent/scripts/js` remain untouched pending a separate consumer
migration task.

## Consequences

- Offline validation is Python compileall and unittest discovery; Node/npm are
  not runtime or release dependencies.
- Future JavaScript consumers should invoke the stable Python CLI/service
  boundary or request a thin adapter that delegates to it. They must not add a
  second Codex client implementation here.
- The prior JS stdin/stdout contract is not maintained by this repository.
