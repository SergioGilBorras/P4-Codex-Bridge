"""Strict offline checks for native web-search event receipts."""
import json
import unittest

from p4_codex_bridge.web_page_receipts import collect_web_receipts, safe_public_url


def record(kind, item):
    return json.dumps({"type": kind, "item": item}).encode() + b"\n"


class WebReceiptsTests(unittest.TestCase):
    def test_event_source_discovery_is_observed_not_verified(self):
        raw = record("item.completed", {
            "type": "web_search", "action": {"type": "search", "query": "secret query not exported"},
            "results": [
                {"url": "https://docs.python.org/3/library/asyncio.html", "snippet": "do not export"},
                {"url": "https://docs.python.org/3/library/asyncio.html"},
                {"url": "https://127.0.0.1/private"},
                {"url": "http://example.com/no"},
                {"url": "https://example.com/?token=secret"},
                {"url": "https://x.local/no"},
            ],
        })
        receipts = collect_web_receipts(raw)
        self.assertEqual(receipts, [{
            "kind": "WEB_SEARCH_EVENT_OBSERVED",
            "operation": "search",
            "source_urls": ["https://docs.python.org/3/library/asyncio.html"],
            "page_content_confirmed": False,
        }])
        self.assertNotIn("secret", repr(receipts))
        self.assertNotIn("snippet", repr(receipts))

    def test_open_is_not_content_confirmation(self):
        raw = record("item.completed", {"type": "web_search",
            "action": {"type": "open_page", "url": "https://example.org/about"},
        })
        receipts = collect_web_receipts(raw)
        self.assertEqual(receipts[0]["operation"], "open_page")
        self.assertEqual(receipts[0]["source_urls"], ["https://example.org/about"])
        self.assertFalse(receipts[0]["page_content_confirmed"])

    def test_missing_results_unknown_actions_and_self_report(self):
        raw = (
            record("item.completed", {"type": "agent_message", "text": "https://not-a-real-source.test"}) +
            record("item.started", {"type": "web_search", "results": [{"url": "https://example.com"}]}) +
            record("item.completed", {"type": "web_search", "action": {"type": "other"},
                                      "results": [{"url": "https://example.org"}]})
        )
        self.assertEqual(collect_web_receipts(raw), [{
            "kind": "WEB_SEARCH_EVENT_OBSERVED", "operation": "unknown",
            "source_urls": ["https://example.org"], "page_content_confirmed": False,
        }])

    def test_reject_sensitive_urls(self):
        bad = ["http://example.com", "https://a:b@example.com/",
               "https://example.com:443/path", "https://localhost/",
               "https://example.internal/path", "https://192.168.1.2/",
               "https://[::1]/", "https://example.com/?key=1",
               "https://example.com/#secret", "https://user@example.com/",
               "https://example.com/" + "x" * 1000, "https://example.com\\@evil.com",
               "https://example.com/users/alice/license",
               "https://example.com/download?token=abc",
               "https://example.com/files/%70assword",
               "https://example.com/api_key/xyz",
               "https://example.com/credentials.json",
               "https://example.com/@private/path",
               "https://example.com/files/password=abc"]
        for url in bad:
            with self.subTest(url=url[:70]):
                self.assertIsNone(safe_public_url(url))

    def test_bounds_and_malformed_lines(self):
        event = record("item.completed", {"type": "web_search", "action": {"type": "search"}})
        receipts = collect_web_receipts(b"broken\n" + b"x" * 65537 + b"\n" + event * 50)
        self.assertEqual(len(receipts), 24)


if __name__ == "__main__":
    unittest.main()
