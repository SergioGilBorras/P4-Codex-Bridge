"""Offline provenance tests: events are observations, assistant prose is not."""
import json
import unittest

from p4_codex_bridge.models import RunResult
from p4_codex_bridge.web_provenance import (
    extract_web_observations, safe_public_https_url,
)


def event(item):
    return (json.dumps({"type": "item.completed", "item": item}) + "\n").encode()


class WebProvenanceTests(unittest.TestCase):
    def test_search_and_page_open_are_distinct_and_not_verified(self):
        raw = (event({"type": "web_search", "action": {"type": "search", "query": "do not persist"},
                      "results": [{"url": "https://docs.python.org/3/library/"}, {"url": "https://docs.python.org/3/other"}]})
               + event({"type": "web_search", "action": {"type": "open_page",
                         "url": "https://github.com/example/project"}, "results": []}))
        result = extract_web_observations(raw)
        self.assertEqual(result["status"], "SEARCH_OBSERVED")
        self.assertEqual(result["sources"], [
            {"state": "SOURCE_DISCOVERED", "origin": "https://docs.python.org/"},
            {"state": "PAGE_OPEN_OBSERVED", "origin": "https://github.com/"},
        ])
        self.assertFalse(result["page_content_confirmed"])
        self.assertNotIn("do not persist", json.dumps(result))
        self.assertNotIn("/library/", json.dumps(result))

    def test_no_observed_search_does_not_promote_assistant_urls(self):
        result = extract_web_observations(event(
            {"type": "agent_message", "text": "I checked https://example.org/secret"}))
        self.assertEqual(result["status"], "NOT_ATTESTED")
        self.assertEqual(result["sources"], [])

    def test_web_item_missing_action_and_results_attests_only_search(self):
        result = extract_web_observations(event(
            {"type": "web_search", "action": {"type": "other"}, "results": []}))
        self.assertEqual(result["status"], "SEARCH_OBSERVED")
        self.assertEqual(result["sources"], [])

    def test_secret_bearing_and_private_urls_are_rejected(self):
        bad = (
            "http://example.org/page", "https://localhost/path",
            "https://127.0.0.1:443/", "https://192.168.1.5/foo",
            "https://user:pass@example.com/", "https://example.com/?token=abc",
            "https://example.com/#private", "https://example.com:8443/",
            "https://metadata.internal/path", "https://example.com/space here",
            "https://example.com/" + "x" * 900,
        )
        for url in bad:
            with self.subTest(url=url[:50]):
                self.assertIsNone(safe_public_https_url(url))

    def test_overlong_records_and_bounded_events(self):
        overlong = event({"type": "web_search", "action": {"type": "search"},
                          "results": [{"url": "https://public.example.org/x"}] * 100})
        observed = extract_web_observations(overlong)
        self.assertLessEqual(len(observed["sources"]), 16)
        oversized = extract_web_observations(b"x" * 1_100_000)
        self.assertTrue(oversized["truncated"])
        self.assertEqual(oversized["status"], "NOT_ATTESTED")

    def test_run_result_remains_compatible_with_old_payload(self):
        old = RunResult(ok=True, bridge_run_id="br_1", exit_code=0, content="ok", stderr="")
        self.assertIsNone(old.web_observations)
        self.assertIsNone(old.web_receipts)
        attached = RunResult(ok=True, bridge_run_id="br_1", exit_code=0, content="ok",
                             stderr="", web_observations=extract_web_observations(b""))
        self.assertEqual(attached.web_observations["status"], "NOT_ATTESTED")
        self.assertIsNone(attached.web_receipts)


if __name__ == "__main__":
    unittest.main()
