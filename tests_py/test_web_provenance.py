"""Offline provenance tests: events are observations, assistant prose is not."""
import hashlib
import json
import unittest

from p4_codex_bridge.models import RunResult
from p4_codex_bridge.web_provenance import (
    extract_web_observations, safe_public_https_url, safe_public_page_url, to_p4_web_receipts,
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
            {"state": "SOURCE_DISCOVERED", "origin": "https://docs.python.org/", "page_url": "https://docs.python.org/3/library/", "url_sha256": hashlib.sha256(b"https://docs.python.org/3/library/").hexdigest()},
            {"state": "SOURCE_DISCOVERED", "origin": "https://docs.python.org/", "page_url": "https://docs.python.org/3/other", "url_sha256": hashlib.sha256(b"https://docs.python.org/3/other").hexdigest()},
            {"state": "PAGE_OPEN_OBSERVED", "origin": "https://github.com/"},
        ])
        self.assertFalse(result["page_content_confirmed"])
        self.assertNotIn("do not persist", json.dumps(result))
        self.assertFalse(result["page_content_confirmed"])

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

    def test_consumer_receipts_match_p4_without_claiming_page_verification(self):
        observations = extract_web_observations(
            event({"type": "web_search", "action": {"type": "open_page",
                  "url": "https://docs.python.org/3/library/"}})
        )
        receipts = to_p4_web_receipts(observations)
        self.assertEqual(receipts, [{
            "kind": "WEB_SEARCH_EVENT_OBSERVED",
            "operation": "open_page",
            "source_urls": ["https://docs.python.org/3/library/"],
            "page_content_confirmed": False,
            "url_sha256": hashlib.sha256(b"https://docs.python.org/3/library/").hexdigest(),
        }])
        self.assertEqual(to_p4_web_receipts({"sources": [
            {"state": "SOURCE_DISCOVERED", "origin": "https://127.0.0.1/"},
            {"state": "SOURCE_DISCOVERED", "origin": "https://example.org/?api_key=x"},
            {"state": "PAGE_CONTENT_CONFIRMED", "origin": "https://example.org/"},
        ]}), [])

    def test_exact_public_documentation_link_and_untrusted_paths(self):
        accepted = (
            "https://docs.python.org/3/library/asyncio.html",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP",
        )
        for url in accepted:
            with self.subTest(url=url):
                self.assertEqual(safe_public_page_url(url), url)
        rejected = (
            "https://github.com/example/private-project",
            "https://docs.python.org/account/secret",
            "https://docs.python.org/3/library/%2e%2e/secret",
            "https://docs.python.org/3/library/?access_token=abc",
            "https://docs.python.org/private/internal",
            "https://docs.python.org/path/" + "a" * 64,
        )
        for url in rejected:
            with self.subTest(url=url):
                self.assertIsNone(safe_public_page_url(url))

    def test_source_without_exact_page_remains_a_domain_hint(self):
        observations = extract_web_observations(event({
            "type": "web_search",
            "action": {"type": "open_page", "url": "https://github.com/example/project"},
        }))
        self.assertEqual(observations["sources"], [{
            "state": "PAGE_OPEN_OBSERVED", "origin": "https://github.com/",
        }])
        self.assertEqual(to_p4_web_receipts(observations)[0]["source_urls"], ["https://github.com/"])

    def test_tampered_public_page_is_never_forwarded(self):
        self.assertEqual(to_p4_web_receipts({"sources": [{
            "state": "SOURCE_DISCOVERED",
            "origin": "https://docs.python.org/",
            "page_url": "https://docs.python.org/private/token",
        }]}), [])

    def test_receipt_rejects_cross_origin_exact_page(self):
        # Two individually safe locators must not be combined into fake provenance.
        self.assertEqual(to_p4_web_receipts({"sources": [{
            "state": "PAGE_OPEN_OBSERVED",
            "origin": "https://github.com/",
            "page_url": "https://docs.python.org/3/library/",
        }]}), [])
        self.assertEqual(to_p4_web_receipts({"sources": [{
            "state": "SOURCE_DISCOVERED",
            "origin": "https://docs.python.org/",
            "page_url": "https://developer.mozilla.org/en-US/docs/Web/HTTP",
        }]}), [])
        self.assertEqual(to_p4_web_receipts({"sources": [{
            "state": "SOURCE_DISCOVERED",
            "origin": "https://docs.python.org/",
            "page_url": "https://docs.python.org/3/library/",
        }]}), [{
            "kind": "WEB_SEARCH_EVENT_OBSERVED",
            "operation": "search",
            "source_urls": ["https://docs.python.org/3/library/"],
            "page_content_confirmed": False,
        }])

    def test_safe_exact_page_hash_is_additive_and_correlated(self):
        import hashlib
        url = "https://docs.python.org/3/library/asyncio.html"
        observed = extract_web_observations(event({
            "type": "web_search",
            "action": {"type": "open_page", "url": url},
        }))
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        self.assertEqual(observed["sources"][0]["url_sha256"], digest)
        receipt = to_p4_web_receipts(observed)[0]
        self.assertEqual(receipt["source_urls"], [url])
        self.assertEqual(receipt["url_sha256"], digest)
        self.assertIs(receipt["page_content_confirmed"], False)
        tampered = {"sources": [{
            **observed["sources"][0],
            "url_sha256": "0" * 64,
        }]}
        self.assertEqual(to_p4_web_receipts(tampered), [])
        origin_only = {"sources": [{"state": "SOURCE_DISCOVERED",
                                   "origin": "https://github.com/", "url_sha256": digest}]}
        self.assertEqual(to_p4_web_receipts(origin_only), [])

    def test_untrusted_paths_never_gain_fingerprints(self):
        observed = extract_web_observations(event({
            "type": "web_search",
            "action": {"type": "open_page",
                       "url": "https://github.com/private-repository/secret-token"},
        }))
        self.assertEqual(observed["sources"], [{
            "state": "PAGE_OPEN_OBSERVED", "origin": "https://github.com/",
        }])
        self.assertNotIn("url_sha256", to_p4_web_receipts(observed)[0])

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
