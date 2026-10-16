"""Repository layout, metadata and licensing contract; no external calls."""
from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProjectLayoutTests(unittest.TestCase):
    def test_documented_top_level_directories_and_license(self) -> None:
        for name in ("bin", "examples", "p4_codex_bridge", "docs", "tests"):
            with self.subTest(directory=name):
                self.assertTrue((ROOT / name / "README.md").is_file())
        for name in ("LICENSE", "AUTHORS.md", "CONTRIBUTORS.md"):
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).is_file())
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text(encoding="utf-8"))

    def test_package_metadata_and_pinned_dependency(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = data["project"]
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project["authors"], [{"name": "Sergio Gil-Borrás"}])
        self.assertEqual(project["readme"], "README.md")
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertTrue(any(
            spec.startswith("portable-tempdirs @ git+https://github.com/SergioGilBorras/portable-tempdirs.git@")
            and len(spec.rsplit("@", 1)[1]) == 40
            for spec in project["dependencies"]
        ))

    def test_unified_offline_and_manual_test_layout(self) -> None:
        self.assertFalse((ROOT / "tests_py").exists())
        self.assertFalse((ROOT / "tests_real").exists())
        self.assertTrue((ROOT / "tests" / "unit" / "_portable_temp.py").is_file())
        self.assertTrue((ROOT / "tests" / "fixtures" / "app_server_schema" / "malformed.json").is_file())
        self.assertTrue((ROOT / "tests" / "manual" / "smoke_codex.py").is_file())
        workflow = (ROOT / ".github" / "workflows" / "offline-tests.yml").read_text(encoding="utf-8")
        self.assertIn("unittest discover -s tests/unit -v", workflow)
        self.assertNotIn("unittest discover -s tests/manual", workflow)


if __name__ == "__main__":
    unittest.main()
