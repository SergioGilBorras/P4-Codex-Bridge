# Offline unit tests

The `test_*.py` modules cover the bridge CLI, runtime, scheduler, service, security, app-server, temporary directories, docs and launcher behavior with fake subprocesses and local SQLite fixtures.

Run from the repository root with `python -m unittest discover -s tests/unit -v`. The `_portable_temp.py` helper uses the pinned portable-tempdirs library to manage disposable directories. Do not add live Codex calls here.
