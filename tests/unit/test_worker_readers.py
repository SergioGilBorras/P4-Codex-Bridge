"""Bounded stdout collection must not wait for potentially blocked event journaling."""
from __future__ import annotations

import io
import threading
import unittest

from p4_codex_bridge._worker import _read_limited


class WorkerReaderTests(unittest.TestCase):
    def test_stdout_remains_available_while_event_persistence_is_blocked(self):
        payload = b'{"type":"item.completed","item":{"type":"agent_message","text":"ready"}}\n'
        output = bytearray()
        locked = threading.Lock()
        exceeded = threading.Event()
        sink_called = threading.Event()
        release_sink = threading.Event()

        def blocked_event_sink(line: bytes) -> None:
            self.assertEqual(line, payload.rstrip(b"\n"))
            sink_called.set()
            release_sink.wait(5)

        reader = threading.Thread(
            target=_read_limited,
            args=(io.BytesIO(payload), output, locked, exceeded, blocked_event_sink),
            daemon=True,
        )
        reader.start()
        try:
            self.assertTrue(sink_called.wait(2), "reader did not observe the Codex event")
            with locked:
                self.assertEqual(bytes(output), payload, "raw stdout must be captured before journal writes")
            self.assertFalse(exceeded.is_set())
        finally:
            release_sink.set()
            reader.join(timeout=3)
        self.assertFalse(reader.is_alive())


if __name__ == "__main__":
    unittest.main()
