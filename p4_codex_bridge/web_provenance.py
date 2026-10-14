"""Bounded, privacy-safe observations of native Codex exec web-search events.

Only a matching JSONL event is an observation. Assistant prose is never evidence.
No search queries, page text, auth data, or model reasoning are persisted.
"""
from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit

MAX_EVENTS = 256
MAX_SOURCES = 16
MAX_URL_LENGTH = 768
MAX_JSONL_BYTES = 1_048_576


def safe_public_https_url(value: object) -> str | None:
    if not isinstance(value, str) or not (1 <= len(value) <= MAX_URL_LENGTH):
        return None
    if any(ord(c) < 33 or ord(c) == 127 for c in value):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or parts.query or parts.fragment or parts.path.startswith("//")):
            return None
        host = parts.hostname
        if host != host.encode("ascii").decode("ascii") or not host or "." not in host:
            return None
        if host.endswith((".local", ".internal", ".localhost", ".test", ".invalid", ".example")):
            return None
        if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in host):
            return None
        if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in host.split(".")):
            return None
        try:
            ipaddress.ip_address(host.strip("[]"))
            return None
        except ValueError:
            pass
        # For an untrusted URL: do not preserve path/query from a potentially
        # secret-bearing task. A hostname-only locator is not a page citation.
        return f"https://{host}/"
    except (ValueError, UnicodeError):
        return None


def extract_web_observations(raw: bytes) -> dict[str, object]:
    """Return conservative hostname observations from explicit web_search JSONL.

    A hostname is a discovery hint only, never an attested exact page URL.
    """
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    observed = False
    truncated = len(raw) > MAX_JSONL_BYTES
    # Reading only the first bounded bytes also prevents scanning unlimited output.
    for line in raw[:MAX_JSONL_BYTES].splitlines()[:MAX_EVENTS]:
        if len(line) > 32_768:
            truncated = True
            continue
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "web_search":
            continue
        observed = True
        action = item.get("action")
        if not isinstance(action, dict):
            continue
        kind = action.get("type")
        if kind not in ("search", "open_page", "find_in_page"):
            continue
        values: list[object] = []
        if kind == "open_page":
            values.append(action.get("url"))
        results = item.get("results")
        if isinstance(results, list):
            for result in results[:MAX_SOURCES]:
                if isinstance(result, dict):
                    values.append(result.get("url"))
        for val in values:
            origin = safe_public_https_url(val)
            if origin is None:
                continue
            state = "PAGE_OPEN_OBSERVED" if kind == "open_page" and val == action.get("url") else "SOURCE_DISCOVERED"
            key = (state, origin)
            if key in seen:
                continue
            seen.add(key)
            if len(sources) == MAX_SOURCES:
                truncated = True
                break
            sources.append({"state": state, "origin": origin})
        if len(sources) == MAX_SOURCES:
            break
    return {
        "status": "SEARCH_OBSERVED" if observed else "NOT_ATTESTED",
        "sources": sources,
        "truncated": truncated,
        "page_content_confirmed": False,
    }


def to_p4_web_receipts(observations: object) -> list[dict[str, object]]:
    """Project observed public-domain leads into P4's existing receipt schema.

    This is not a statement that a URL's page or information was verified.
    """
    if not isinstance(observations, dict):
        return []
    source_items = observations.get("sources")
    if not isinstance(source_items, list):
        return []
    receipts: list[dict[str, object]] = []
    for source in source_items[:MAX_SOURCES]:
        if not isinstance(source, dict):
            continue
        origin = source.get("origin")
        state = source.get("state")
        if safe_public_https_url(origin) != origin or state not in ("PAGE_OPEN_OBSERVED", "SOURCE_DISCOVERED"):
            continue
        receipts.append({
            "kind": "WEB_SEARCH_EVENT_OBSERVED",
            "operation": "open_page" if state == "PAGE_OPEN_OBSERVED" else "search",
            "source_urls": [origin],
            "page_content_confirmed": False,
        })
    return receipts
