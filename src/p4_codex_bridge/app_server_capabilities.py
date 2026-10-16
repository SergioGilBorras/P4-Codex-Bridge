"""Installed app-server schema discovery and feature preflight.

The protocol is experimental. Discovery uses the installed Codex executable's
JSON schema generator; failures are represented as UNKNOWN, never as absence.
"""
from __future__ import annotations

import json
import hashlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from portable_tempdirs import temporary_directory

from .runtime import codex_environment, resolve_codex_command


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_WITH_LIMITATIONS = "SUPPORTED_WITH_LIMITATIONS"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


# Explicit root-export name disambiguates protocol evidence from the generic
# version compatibility capability enum.
AppServerCapabilityStatus = CapabilityStatus


FEATURE_METHODS: dict[str, tuple[str, ...]] = {
    "app_server.initialize": ("initialize",),
    "app_server.thread.create": ("thread/start",),
    "app_server.thread.resume": ("thread/resume",),
    "app_server.thread.fork": ("thread/fork",),
    "app_server.turn.start": ("turn/start",),
    "app_server.turn.steer": ("turn/steer",),
    "app_server.turn.interrupt": ("turn/interrupt",),
    "app_server.approvals": ("item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                              "item/permissions/requestApproval"),
    "app_server.skills.list": ("skills/list",),
    "app_server.models.list": ("model/list",),
    "app_server.turns.list": ("thread/turns/list",),
    "app_server.structured_output": ("turn/start",),
    "app_server.usage_events": ("thread/tokenUsage/updated",),
    "app_server.config.read": ("config/read",),
    "app_server.mcp.list": ("mcpServerStatus/list",),
    "app_server.review.start": ("review/start",),
    "app_server.thread.read": ("thread/read",),
    "app_server.items.list": ("thread/items/list",),
}
# Public bridge features are deliberately mapped to concrete wire methods. The
# schema generator is experimental; the mapping is parser-owned and versioned.
BRIDGE_CAPABILITY_RPC_METHODS = FEATURE_METHODS
REQUIRED_APP_SERVER_CAPABILITIES = (
    "app_server.thread.create",
    "app_server.turn.start",
)
OPTIONAL_APP_SERVER_CAPABILITIES = tuple(
    name for name in FEATURE_METHODS
    if name not in {"app_server.initialize", *REQUIRED_APP_SERVER_CAPABILITIES}
)
BRIDGE_SCHEMA_PARSER_VERSION = "1"
FEATURE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "app_server.structured_output": ("outputSchema",),
}


@dataclass(frozen=True)
class AppServerSchemaSnapshot:
    codex_version: str | None
    source_type: str
    source_identity: str | None
    discovered_methods: tuple[str, ...]
    generated_at: str
    bridge_parser_version: str = BRIDGE_SCHEMA_PARSER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "codex_version": self.codex_version,
            "source_type": self.source_type,
            "source_identity": self.source_identity,
            "discovered_methods": list(self.discovered_methods),
            "generated_at": self.generated_at,
            "bridge_parser_version": self.bridge_parser_version,
        }


@dataclass(frozen=True)
class AppServerCapabilitySet:
    statuses: dict[str, CapabilityStatus]
    source: str
    protocol_version: str | None = None
    error: str | None = None
    schema_snapshot: AppServerSchemaSnapshot | None = None
    runtime_confirmed_methods: tuple[str, ...] = ()

    def status(self, feature: str) -> CapabilityStatus:
        return self.statuses.get(feature, CapabilityStatus.UNKNOWN)

    def require(self, feature: str) -> None:
        status = self.status(feature)
        if status not in {CapabilityStatus.SUPPORTED, CapabilityStatus.SUPPORTED_WITH_LIMITATIONS}:
            from .errors import CapabilityUnavailableError
            raise CapabilityUnavailableError(f"Codex app-server capability {feature} is {status.value}")

    def confirm_runtime_method(self, method: str, *, params: dict[str, Any] | None = None) -> "AppServerCapabilitySet":
        """Promote only capabilities directly exercised successfully at runtime."""
        statuses = dict(self.statuses)
        confirmed = set(self.runtime_confirmed_methods)
        confirmed.add(method)
        for feature, methods in FEATURE_METHODS.items():
            if method not in methods:
                continue
            if feature == "app_server.approvals":
                statuses[feature] = (CapabilityStatus.SUPPORTED
                    if set(methods).issubset(confirmed) else CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
            elif feature == "app_server.structured_output":
                if method == "turn/start" and params and "outputSchema" in params:
                    statuses[feature] = CapabilityStatus.SUPPORTED
            else:
                statuses[feature] = CapabilityStatus.SUPPORTED
        return AppServerCapabilitySet(statuses, self.source, self.protocol_version,
                                      self.error, self.schema_snapshot, tuple(sorted(confirmed)))

    def reject_runtime_method(self, method: str) -> "AppServerCapabilitySet":
        """Record explicit JSON-RPC method-not-found evidence, not transport errors."""
        statuses = dict(self.statuses)
        for feature, methods in FEATURE_METHODS.items():
            if method in methods and feature != "app_server.structured_output":
                statuses[feature] = (CapabilityStatus.SUPPORTED_WITH_LIMITATIONS
                                     if feature == "app_server.approvals"
                                     else CapabilityStatus.UNSUPPORTED)
        return AppServerCapabilitySet(statuses, self.source, self.protocol_version,
                                      self.error, self.schema_snapshot, self.runtime_confirmed_methods)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "protocol_version": self.protocol_version,
                "error": self.error,
                "schema_snapshot": self.schema_snapshot.to_dict() if self.schema_snapshot else None,
                "runtime_confirmed_methods": list(self.runtime_confirmed_methods),
                "required_capabilities": list(REQUIRED_APP_SERVER_CAPABILITIES),
                "optional_capabilities": list(OPTIONAL_APP_SERVER_CAPABILITIES),
                "features": {key: value.value for key, value in sorted(self.statuses.items())}}


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"method", "rpcmethod", "jsonrpcmethod"}:
                if isinstance(item, str):
                    yield item
                elif isinstance(item, dict):
                    yield from _walk_method_schema(item)
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _walk_method_schema(value: Any) -> Iterable[str]:
    """Read only literal JSON-Schema method values, never descriptions/examples."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "const" and isinstance(item, str):
                yield item
            elif key == "enum" and isinstance(item, list):
                yield from (entry for entry in item if isinstance(entry, str))
            elif key in {"oneOf", "anyOf"}:
                yield from _walk_method_schema(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_method_schema(item)


def _method_scoped_fields(value: Any) -> dict[str, set[str]]:
    fields: dict[str, set[str]] = {}
    if isinstance(value, dict):
        method_values = []
        if "method" in value:
            method_values = list(_walk_method_schema(value["method"])) if isinstance(value["method"], (dict, list)) else [value["method"]]
        properties = value.get("properties")
        if isinstance(properties, dict) and "method" in properties:
            field_method = properties["method"]
            method_values.extend(list(_walk_method_schema(field_method)) if isinstance(field_method, (dict, list)) else [field_method])
        keys = set(_walk_keys(value))
        for method in method_values:
            if isinstance(method, str):
                fields.setdefault(method, set()).update(keys)
        for item in value.values():
            _merge_method_fields(fields, _method_scoped_fields(item))
    elif isinstance(value, list):
        for item in value:
            fields = _merge_method_fields(fields, _method_scoped_fields(item))
    return fields


def _merge_method_fields(target: dict[str, set[str]], source: dict[str, set[str]]) -> dict[str, set[str]]:
    for method, keys in source.items():
        target.setdefault(method, set()).update(keys)
    return target


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def parse_schema_capabilities(schema_paths: Iterable[Path], *, protocol_version: str | None = None,
                              codex_version: str | None = None,
                              source_type: str = "GENERATED_LOCAL_SCHEMA") -> AppServerCapabilitySet:
    observed: set[str] = set()
    method_fields: dict[str, set[str]] = {}
    digest = hashlib.sha256()
    try:
        ordered_paths = sorted((Path(path) for path in schema_paths), key=lambda p: p.name.casefold())
        for path in ordered_paths:
            raw = path.read_bytes()
            digest.update(path.name.encode("utf-8"))
            digest.update(raw)
            data = json.loads(raw.decode("utf-8"))
            observed.update(_walk_strings(data))
            method_fields = _merge_method_fields(method_fields, _method_scoped_fields(data))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        return AppServerCapabilitySet({key: CapabilityStatus.UNKNOWN for key in FEATURE_METHODS},
                                      source_type, protocol_version, type(exc).__name__)
    statuses: dict[str, CapabilityStatus] = {}
    for feature, methods in FEATURE_METHODS.items():
        matched = [method for method in methods if method in observed]
        required_fields = FEATURE_REQUIRED_FIELDS.get(feature, ())
        if required_fields and matched and not any(set(required_fields).issubset(method_fields.get(method, set())) for method in matched):
            statuses[feature] = CapabilityStatus.UNKNOWN
        elif matched:
            statuses[feature] = CapabilityStatus.SUPPORTED
        elif observed:
            statuses[feature] = CapabilityStatus.UNSUPPORTED
        else:
            statuses[feature] = CapabilityStatus.UNKNOWN
    snapshot = AppServerSchemaSnapshot(
        codex_version=codex_version,
        source_type=source_type,
        source_identity=digest.hexdigest() if ordered_paths else None,
        discovered_methods=tuple(sorted(observed)),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    # A schema proves that a method is described by this local installation,
    # not that the running server accepts it. Preserve that limitation.
    statuses = {name: (CapabilityStatus.SUPPORTED_WITH_LIMITATIONS
                       if status == CapabilityStatus.SUPPORTED else status)
                for name, status in statuses.items()}
    return AppServerCapabilitySet(statuses, source_type, protocol_version, schema_snapshot=snapshot)


def discover_app_server_capabilities(*, command: list[str] | None = None, timeout: float = 10) -> AppServerCapabilitySet:
    selected = command or resolve_codex_command()
    try:
        version_text = None
        try:
            version_result = subprocess.run(selected + ["--version"], capture_output=True, text=True,
                timeout=min(timeout, 5), shell=False, env=codex_environment())
            if version_result.returncode == 0:
                version_text = version_result.stdout.strip() or version_result.stderr.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            pass
        # Keep generated schema data in the established system-temp parent.
        # The library fails closed there; it does not switch to another root.
        with temporary_directory("P4CodexSchema", parent=Path(tempfile.gettempdir())) as tmp:
            output = Path(tmp)
            result = subprocess.run(selected + ["app-server", "generate-json-schema", "--out", str(output), "--experimental"],
                                    capture_output=True, text=True, timeout=timeout, shell=False,
                                    env=codex_environment())
            if result.returncode != 0:
                return AppServerCapabilitySet({key: CapabilityStatus.UNKNOWN for key in FEATURE_METHODS},
                    "NOT_AVAILABLE", error="schema_generator_failed")
            paths = tuple(output.rglob("*.json"))
            if not paths:
                return AppServerCapabilitySet({key: CapabilityStatus.UNKNOWN for key in FEATURE_METHODS},
                    "NOT_AVAILABLE", error="schema_files_missing")
            return parse_schema_capabilities(paths, source_type="GENERATED_LOCAL_SCHEMA",
                                             codex_version=version_text)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return AppServerCapabilitySet({key: CapabilityStatus.UNKNOWN for key in FEATURE_METHODS},
                                      "NOT_AVAILABLE", error=type(exc).__name__)
