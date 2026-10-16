"""Local documentation links and the operator CLI help are checked offline."""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DocumentationAndHelpTests(unittest.TestCase):
    def test_local_markdown_links_exist(self):
        paths = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CONTRIBUTORS.md", *sorted((ROOT / "docs").rglob("*.md")), *sorted((ROOT / "tests").rglob("README.md")), ROOT / "src" / "README.md", ROOT / "bin" / "README.md", ROOT / "examples" / "README.md", ROOT / "src" / "p4_codex_bridge" / "README.md"]
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

    def test_operator_cli_help_has_no_model_call(self):
        result = subprocess.run(
            [sys.executable, "-m", "p4_codex_bridge", "--help"],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--help", result.stdout)


if __name__ == "__main__":
    unittest.main()
