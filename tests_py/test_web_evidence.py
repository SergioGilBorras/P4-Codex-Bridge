"""Offline attestations: web URLs come from native tool events, never model text."""
from __future__ import annotations

import unittest

from p4_codex_bridge.web_evidence import MAX_RECEIPTS, WebEvidenceCollector, safe_source_url


def completed(item):
    return {"type": "item.completed", "item": {"type": "web_search", **item}}


class WebEvidenceTests(unittest.TestCase):
    def test_url_policy_rejects_private_query_and_sensitive_origins(self):
        unsafe = (
            "http://docs.python.org/library/", "https://127.0.0.1/data",
            "https://10.1.2.3/file", "https://localhost/a",
            "https://host.local/info", "https://user:password@docs.python.org/",
            "https://docs.python.org:8443/", "https://docs.python.org/?access_token=abc",
            "https://docs.python.org/#private", "file:///etc/passwd",
            "https://docs.python.org/private/token/abc", "https://docs.python.org/\\evil",
            "https://docs.python.org/" + "x" * 2048,
            "https://[::1]/", "https://example.com@localhost/x",
            "https://example.com/a b", "https://example.com/a\nsecret",
        )
        for url in unsafe:
            with self.subTest(url=url[:70]):
                self.assertIsNone(safe_source_url(url))
        self.assertEqual(safe_source_url("https://Docs.Python.Org/library/abc"), "https://docs.python.org/library/abc")

    def test_only_native_item_tool_events_are_attested(self):
        c = WebEvidenceCollector("br_unit")
        c.observe({"type": "item.completed", "item": {"type": "agent_message", "text": "https://example.com/a"}})
        c.observe({"type": "item.completed", "item": {"type": "web_search", "action": {"type": "other"}, "results": [{"url": "https://example.com/a"}]}})
        self.assertEqual(c.status, "SEARCH_OBSERVED")
        self.assertEqual(c.receipts, [])
        c.observe(completed({"action": {"type": "search"}, "results": [
            {"url": "https://docs.python.org/library/"}, {"url": "https://docs.python.org/?secret=abc"},
            {"url": "https://docs.python.org/library/"}]}))
        self.assertEqual(c.status, "SOURCE_DISCOVERED")
        self.assertEqual(len(c.receipts), 1)
        self.assertEqual(c.receipts[0]["status"], "SOURCE_DISCOVERED")
        self.assertEqual(c.receipts[0]["bridge_run_id"], "br_unit")
        self.assertTrue(c.receipts[0]["evidence_id"].startswith("web_"))
        self.assertNotIn("secret", str(c.receipts))

        c.observe(completed({"action": {"type": "open_page", "url": "https://docs.python.org/library/"}, "status": "failed"}))
        self.assertEqual(len(c.receipts), 1)
        c.observe(completed({"action": {"type": "open_page", "url": "https://docs.python.org/library/"}, "status": "completed"}))
        self.assertEqual(c.status, "PAGE_OPEN_OBSERVED")
        self.assertEqual(c.receipts[1]["status"], "PAGE_OPEN_OBSERVED")
        self.assertNotIn("PAGE_CONTENT_CONFIRMED", str(c.receipts))

    def test_bounded_sources_deduplicated_and_no_query_text(self):
        c = WebEvidenceCollector("br_limits")
        c.observe(completed({"action": {"type": "search", "query": "PRIVATE PROJECT INTERNAL SECRET"}, "results": [
            {"url": f"https://public.example.com/{i}"} for i in range(100)
        ]}))
        self.assertEqual(len(c.receipts), MAX_RECEIPTS)
        self.assertNotIn("PRIVATE", str(c.receipts))
        self.assertEqual(c.status, "SOURCE_DISCOVERED")
        c.observe(completed({"action": {"type": "search"}, "results": [
            {"url": "https://public.example.com/1"}
        ]}))
        self.assertEqual(len(c.receipts), MAX_RECEIPTS)

    def test_no_web_events_is_not_attested(self):
        c = WebEvidenceCollector("br_empty")
        c.observe(None)
        c.observe({"type": "item.completed", "item": {"type": "web_search", "action": {"type": "search"}}})
        self.assertEqual(c.status, "SEARCH_OBSERVED")
        self.assertEqual(c.receipts, [])
        self.assertEqual(WebEvidenceCollector("br_new").status, "NOT_ATTESTED")


if __name__ == "__main__":
    unittest.main()
