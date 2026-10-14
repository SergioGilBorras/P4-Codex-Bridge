# Native Codex web-search observations

Bridge can request `web_search=disabled|cached|indexed|live` on a supported isolated exec. **A configured tool is not a search receipt.** For opted-in runs only, `RunResult.web_observations` optionally contains a bounded, privacy-safe summary extracted from actual `codex exec --json` `item.completed` events with `item.type=web_search`.

```json
{
  "web_observations": {
    "status": "SEARCH_OBSERVED",
    "sources": [
      {"state": "SOURCE_DISCOVERED", "origin": "https://docs.python.org/", "page_url": "https://docs.python.org/3/library/asyncio.html"},
      {"state": "PAGE_OPEN_OBSERVED", "origin": "https://github.com/"}
    ],
    "truncated": false,
    "page_content_confirmed": false
  }
}
```

**The example is synthetic and not an observed run.** Most hosts yield **discovery hints** without page paths. A short, explicit allowlist of public documentation hosts can retain an exact `page_url` with strictly validated path characters, segment lengths and no sensitive segments. Queries, fragments, prompt/search terms, snippets and page bodies are never persisted. The default origin is normalized to `https://hostname/` and private/loopback IPs, non-HTTPS links, user info, unusual ports, query/fragment, invalid characters and oversized URLs are rejected. At most 16 observations and 256 events are inspected within 1 MiB of output. A search item with no observed URL still yields `SEARCH_OBSERVED` with an empty list; a model-written URL yields **no** observed source. `PAGE_OPEN_OBSERVED` means an open-page action appeared, **not** that the page loaded successfully.

`web_observations=null` means no opted-in web collection; `NOT_ATTESTED` means the output did not provide an observed matching web-search event. Some Codex versions do not export page URLs or results in JSONL, so an absence of evidence must stay an absence.

The companion `RunResult.web_receipts` list projects each accepted public source locator (exact page for allowlisted documentation hosts, origin only otherwise) into the P4 adapter-compatible `WEB_SEARCH_EVENT_OBSERVED` shape (`operation`, `source_urls`, `page_content_confirmed=false`). For safely retained exact pages, version 1.4.1 also adds `url_sha256` (SHA-256 over the precise observed HTTPS URL); host-only hints have no digest. A mismatched digest/page pair is rejected, always as an *unverified lead*. The list is `null` when web collection is disabled; empty when no accepted public host was observed. Neither field proves a page was read.

**Not yet delivered:** general page-exact URL receipts for arbitrary sites, proof of successful page loading, page-content provenance and independently corroborated P4 evidence. These require upstream support and matching-run receipts, validation of public URLs without exposing secrets, and independent security review. Consumers must not promote these observations to `VERIFIED` or attach them as citations proving a candidate's API, license, version or safety. External dependency adoption continues to require `HUMAN_REVIEW_REQUIRED`.

The parser is pure and covered by offline tests; CI never runs Codex for it. See [Python API](PYTHON_API.md), [security](SECURITY.md) and [roadmap](ROADMAP.md).
