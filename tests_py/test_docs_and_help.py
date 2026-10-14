"""Local documentation links and the operator CLI help are checked offline."""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DocumentationAndHelpTests(unittest.TestCase):
    def test_local_markdown_links_exist(self):
        paths = [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").rglob("*.md"))]
        broken = []
        for page in paths:
            for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", page.read_text(encoding="utf-8")):
                relative = target.strip().split("#", 1)[0].split("?", 1)[0]
                if not relative or "://" in relative or relative.startswith(("mailto:", "data:", "/")):
                    continue
                if any(c in relative for c in ("<", ">", "{", "}")):
                    continue
                if not (page.parent / relative).exists():
                    broken.append(f"{page.relative_to(ROOT)}: {relative}")
        self.assertFalse(broken, "Broken local documentation links: " + "; ".join(broken))

    def test_repository_keeps_live_smokes_and_fake_examples_separate(self):
        self.assertTrue((ROOT / "tests_real" / "smoke_codex.py").is_file())
        self.assertTrue((ROOT / "examples" / "scheduler_demo.py").is_file())
        self.assertFalse((ROOT / "tests_py" / "smoke_codex.py").exists())
        self.assertFalse((ROOT / "tests_py" / "scheduler_demo.py").exists())
        self.assertFalse((ROOT / "docs" / "TOOLS_CATALOG.md").exists())
        self.assertFalse((ROOT / "docs" / "SKILLS_CATALOG.md").exists())

    def test_operational_docs_do_not_advertise_session_inventory(self):
        paths = [ROOT / "AGENTS.md", ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
        forbidden = (
            "TOOLS_CATALOG.md",
            "SKILLS_CATALOG.md",
            "18 skills in this session",
            "tests_py/smoke_codex.py",
            "tests_py/scheduler_demo.py",
        )
        stale = []
        for page in paths:
            text = page.read_text(encoding="utf-8")
            stale.extend(
                f"{page.relative_to(ROOT)}: {item}" for item in forbidden if item in text
            )
        self.assertEqual(stale, [])

    def test_operator_cli_help_has_no_model_call(self):
        result = subprocess.run(
            [sys.executable, "-m", "p4_codex_bridge", "--help"],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--help", result.stdout)


if __name__ == "__main__":
    unittest.main()
