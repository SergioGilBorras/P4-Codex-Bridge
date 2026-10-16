# Tests

The test code lives in one directory, divided by purpose:

- [`unit/`](unit/README.md) — automated, offline `unittest` tests using fake Codex processes and local fixtures. No real model inference.
- [`fixtures/`](fixtures/README.md) — versioned JSON and other inputs used by the automated tests.
- [`manual/`](manual/README.md) — **opt-in** smoke scripts that may contact real Codex and consume usage. These are deliberately outside automated test discovery.

From the repository root, run `python -m unittest discover -s tests/unit -v`. See [test catalog](../docs/TEST_CATALOG.md).
