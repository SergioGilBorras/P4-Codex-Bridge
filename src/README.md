# Python source tree

The installable Python library lives in [`p4_codex_bridge/`](p4_codex_bridge/README.md).

This repository uses the standard `src/` layout: the Python distribution is built from `src/p4_codex_bridge`, while tests, documentation, example programs, packaging metadata and operator scripts remain outside the package.

Install from the repository root with `python -m pip install -e .` for development, or `python -m pip install .` to verify the built distribution. Import as `p4_codex_bridge` or run `python -m p4_codex_bridge` after installation. The public import and executable names are unchanged.
