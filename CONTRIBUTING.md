# Contributing

Please open a GitHub issue to discuss behavior changes, public API updates or security-sensitive work before implementing them. P4-Codex-Bridge is a general-purpose Python bridge to the Codex CLI and app-server; avoid consumer-specific logic or undocumented security assumptions.

Use a feature branch rather than editing `main`, and submit a pull request describing the change, its compatibility and security implications, and the offline tests added or updated. Target Python **3.11+** and update the relevant documentation when behavior changes.

## Local development and validation

From the repository root, use an isolated Python environment:

```bash
python -m pip install -e .
python -m pip install "setuptools>=77" wheel build
python -m unittest discover -s tests/unit -v
python -m build --no-isolation --wheel --sdist --outdir dist
```

The runtime dependency `portable-tempdirs` is pinned to a Git commit; a first install may require Git/network access. These commands only validate the bridge locally; they do not publish a release.

Automated tests must use fake/offline Codex or app-server fixtures and **must not** require external AI credentials, real Codex model inference, paid requests or live web access. Scripts under `tests/manual/` are separately authorized, explicit opt-in checks and must not run in CI by default. See [manual testing](tests/manual/README.md).

Never add tokens, credentials, private source code, personal session data, or proprietary documents to commits, fixtures, logs or pull requests. Preserve documented permission and approval boundaries, conservative recovery and safe web-provenance guarantees. See [security guidance](docs/SECURITY.md).

For authorship, see [AUTHORS.md](AUTHORS.md); for licensing, see [LICENSE](LICENSE).
