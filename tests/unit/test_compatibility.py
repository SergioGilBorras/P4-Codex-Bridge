from __future__ import annotations

import unittest
from enum import StrEnum

from p4_codex_bridge.compatibility import (
    CapabilitySet,
    CodexVersionInfo,
    CompatibilityStatus,
    assess_compatibility,
)
from p4_codex_bridge.models import RunStatus


class CompatibilityTests(unittest.TestCase):
    def test_public_status_enums_use_stdlib_strenum(self):
        self.assertTrue(issubclass(RunStatus, StrEnum))
        self.assertEqual(str(RunStatus.COMPLETED), "COMPLETED")
        self.assertEqual(f"{RunStatus.COMPLETED}", "COMPLETED")

    def test_capability_based_gate_and_version_classification(self):
        caps = CapabilitySet({"exec": {"resume": {"status": "SUPPORTED"}, "fork": False}})
        old = assess_compatibility(CodexVersionInfo.parse("codex-cli 0.160.1"), caps,
                                   required=("exec.resume",))
        self.assertEqual(old.status, CompatibilityStatus.SUPPORTED)
        missing = assess_compatibility(CodexVersionInfo.parse("codex-cli 0.160.1"), caps,
                                       required=("exec.fork",))
        self.assertEqual(missing.status, CompatibilityStatus.UNSUPPORTED)
        newer = assess_compatibility(CodexVersionInfo.parse("codex-cli 0.161.0"), caps,
                                     required=("exec.resume",))
        self.assertEqual(newer.status, CompatibilityStatus.SUPPORTED_WITH_LIMITATIONS)
        unknown = assess_compatibility(CodexVersionInfo.parse("nightly"), caps)
        self.assertEqual(unknown.status, CompatibilityStatus.UNKNOWN_NEWER_VERSION)


if __name__ == "__main__":
    unittest.main()
