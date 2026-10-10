"""Test-only adapter for explicitly owned portable temporary directories.

The platform temporary root is discovered from Python, while
portable-tempdirs creates and removes each child directory. There is no
fallback if creation is denied; tests must have access to that root.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import TracebackType

from portable_tempdirs import TemporaryDirectory as _TemporaryDirectory
from portable_tempdirs import temporary_directory


class TemporaryDirectory:
    """Small tempfile-shaped adapter backed by portable-tempdirs.

    Only the interface used in this test suite is supported: ``name``,
    ``cleanup()``, and the context manager. ``prefix`` is accepted for source
    compatibility but ownership names are generated securely by the library.
    """

    def __init__(self, prefix: str | None = None, dir: str | Path | None = None):
        del prefix
        # tempfile is used only to discover the platform's established temp
        # root; portable-tempdirs creates and owns the actual directory.
        parent = Path(dir).resolve() if dir is not None else Path(tempfile.gettempdir()).resolve()
        if not parent.is_dir():
            raise FileNotFoundError("explicit test temporary parent must exist")
        self._owner: _TemporaryDirectory = temporary_directory(
            "P4BridgeTests", parent=parent
        )
        self.name = self._owner.name

    def cleanup(self) -> None:
        self._owner.cleanup()

    def __enter__(self) -> str:
        return self.name

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return self._owner.__exit__(exc_type, exc_value, traceback)
