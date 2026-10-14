"""Conservative, bounded receipts for Codex exec web-search JSONL events.

A model's final text never counts as an observed source. These receipts attest
only fields of tool events emitted by this particular Codex execution.
"""
from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlsplit

_MAX_EVENTS = 24
_MAX_SOURCES = 8
_MAX_LINE = 65536
_MAX_URL = 512
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")


def safe_public_url(value: object) -> str | None:
    """Retain only bounded public HTTPS URLs without credentials or query tokens."""
    if not isinstance(value, str) or not 1 <= len(value) <= _MAX_URL:
        return None
    if any(ord(c) < 33 or ord(c) > 126 for c in value):
        return None
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower().rstrip(".")
        if (u.scheme != "https" or not host or u.netloc.lower() != host
                or u.username is not None or u.password is not None
                or u.query or u.fragment or not _HOST.fullmatch(host)
                or ".." in host or host in {"localhost", "localhost.localdomain"}
                or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        if "." not in host or len(host.rsplit(".", 1)[-1]) < 2:
            return None
        # Never export URL paths carrying credential-like values, personal
        # identifiers, percent-encoded payloads or local-user paths. A page
        # without a safe public locator is NOT_ATTESTED as a source.
        path = u.path.lower()
        if ("%" in path or "@" in path or "=" in path or ":" in path
                or "\\" in path or "//" in path or
                re.search(r"/(?:users?|home|root|private|secrets?|credentials?|tokens?|passwords?)(?:/|\.|$)", path)
                or re.search(r"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|bearer)", path)):
            return None
    except (ValueError, UnicodeError):
        return None
    return value


def collect_web_receipts(output: bytes) -> list[dict[str, object]]:
    """Only item.completed(web_search) events, never agent_message self-reports."""
    receipts: list[dict[str, object]] = []
    for line in output.splitlines():
        if len(receipts) >= _MAX_EVENTS:
            break
        if len(line) > _MAX_LINE:
            continue
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "web_search":
            continue
        action = item.get("action")
        if isinstance(action, dict):
            kind = action.get("type")
        else:
            kind = action if isinstance(action, str) else None
        operation = kind if kind in {"search", "open_page", "find_in_page"} else "unknown"
        urls: list[str] = []
        candidates = item.get("results")
        if isinstance(candidates, list):
            for result in candidates[:_MAX_SOURCES]:
                if not isinstance(result, dict):
                    continue
                url = safe_public_url(result.get("url"))
                if url and url not in urls:
                    urls.append(url)
        # An open-page action URL is an observation of a requested page, not
        # proof that its contents were returned successfully.
        if operation == "open_page" and isinstance(action, dict):
            url = safe_public_url(action.get("url"))
            if url and url not in urls:
                urls.append(url)
        receipts.append({
            "kind": "WEB_SEARCH_EVENT_OBSERVED",
            "operation": operation,
            "source_urls": urls[:_MAX_SOURCES],
            "page_content_confirmed": False,
        })
    return receipts
