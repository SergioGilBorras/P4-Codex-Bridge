"""Bounded, conservative web-search receipts from native codex exec JSONL.

Only tool events are examined. Never infer page visits from model messages,
prompt text or arbitrary references, and never serialize search queries.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_RECEIPTS = 16
MAX_URL_LENGTH = 1024
MAX_PATH_LENGTH = 512
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_SENSITIVE_PATH = re.compile(r"(?:token|secret|password|api[_-]?key|credential|session|auth)", re.I)


def safe_source_url(value: Any) -> str | None:
    """Reject URL forms capable of disclosing local resources or credentials."""
    if not isinstance(value, str) or len(value) > MAX_URL_LENGTH or not value:
        return None
    if any(ord(ch) < 33 or ord(ch) > 126 or ch == "\\" for ch in value):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme != "https" or not host or not _HOST.fullmatch(host)
                or parsed.username is not None or parsed.password is not None
                or parsed.port is not None or parsed.query or parsed.fragment
                or len(parsed.path) > MAX_PATH_LENGTH):
            return None
        if host.endswith((".local", ".internal", ".localhost")) or host == "localhost":
            return None
        if ".." in host or "." not in host or _SENSITIVE_PATH.search(parsed.path):
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return None
        if parsed.path.startswith("//") or "@" in parsed.path:
            return None
        # Exact URL is retained only for these deliberately restricted forms.
        return urlunsplit(("https", host.lower(), parsed.path or "/", "", ""))
    except (ValueError, UnicodeError):
        return None


class WebEvidenceCollector:
    """An observation is not proof of fetched content, license or suitability."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.search_observed = False
        self.receipts: list[dict[str, str]] = []
        self._seen: set[tuple[str, str]] = set()

    def _add(self, status: str, url: Any) -> None:
        clean = safe_source_url(url)
        if clean is None or len(self.receipts) >= MAX_RECEIPTS:
            return
        key = (status, clean)
        if key in self._seen:
            return
        self._seen.add(key)
        ref = hashlib.sha256(f"{self.run_id}\0{status}\0{clean}".encode()).hexdigest()[:24]
        self.receipts.append({
            "evidence_id": "web_" + ref,
            "bridge_run_id": self.run_id,
            "status": status,
            "url": clean,
            "provenance": "codex_exec.item.completed",
        })

    def observe(self, event: Any) -> None:
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            return
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") not in {"web_search", "webSearch"}:
            return
        self.search_observed = True
        action = item.get("action")
        if not isinstance(action, dict):
            return
        kind = action.get("type")
        if kind in {"search", "web_search"}:
            candidates = item.get("results")
            if not isinstance(candidates, list):
                candidates = action.get("results")
            if isinstance(candidates, list):
                for result in candidates[:MAX_RECEIPTS]:
                    if isinstance(result, dict):
                        self._add("SOURCE_DISCOVERED", result.get("url"))
        elif kind == "open_page":
            # A completed tool action attests an open operation, not that
            # content was successfully retrieved or read by the model.
            if item.get("status") in {"completed", "success"}:
                self._add("PAGE_OPEN_OBSERVED", action.get("url"))
        elif kind == "find_in_page":
            if item.get("status") in {"completed", "success"}:
                self._add("PAGE_FIND_OBSERVED", action.get("url"))

    @property
    def status(self) -> str:
        if not self.search_observed:
            return "NOT_ATTESTED"
        if any(r["status"] == "PAGE_OPEN_OBSERVED" for r in self.receipts):
            return "PAGE_OPEN_OBSERVED"
        if any(r["status"] == "SOURCE_DISCOVERED" for r in self.receipts):
            return "SOURCE_DISCOVERED"
        return "SEARCH_OBSERVED"
