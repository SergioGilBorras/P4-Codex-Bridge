"""Version and capability compatibility records.

Compatibility is based on observed capabilities, not a hard-coded upper version
ceiling. An un-audited newer CLI is reported with limitations when required
features are still observable.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from . import __version__


class CompatibilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_WITH_LIMITATIONS = "SUPPORTED_WITH_LIMITATIONS"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN_NEWER_VERSION = "UNKNOWN_NEWER_VERSION"


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_WITH_LIMITATIONS = "SUPPORTED_WITH_LIMITATIONS"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CodexVersionInfo:
    cli_version: str | None
    bridge_version: str = __version__
    protocol_version: str | None = None
    parsed_cli_version: tuple[int, int, int] | None = None

    @classmethod
    def parse(cls, raw: str | None, *, protocol_version: str | None = None) -> "CodexVersionInfo":
        match = re.search(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?", raw or "")
        parsed = tuple(int(part or 0) for part in match.groups()) if match else None
        return cls(raw.strip() if raw else None, protocol_version=protocol_version,
                   parsed_cli_version=parsed)  # type: ignore[arg-type]


@dataclass(frozen=True)
class CapabilitySet:
    values: Mapping[str, Any] = field(default_factory=dict)
    source: str = "installed-runtime-discovery"

    def status(self, name: str) -> CapabilityStatus:
        value: Any = self.values
        for component in name.split("."):
            if not isinstance(value, Mapping) or component not in value:
                return CapabilityStatus.UNKNOWN
            value = value[component]
        if isinstance(value, Mapping):
            status = value.get("status")
            if status is not None:
                try:
                    return CapabilityStatus(status)
                except ValueError:
                    return CapabilityStatus.UNKNOWN
            if value.get("available") is True:
                return CapabilityStatus.SUPPORTED
            if value.get("available") is False:
                return CapabilityStatus.UNSUPPORTED
            return CapabilityStatus.UNKNOWN
        if value is True:
            return CapabilityStatus.SUPPORTED
        if value is False:
            return CapabilityStatus.UNSUPPORTED
        return CapabilityStatus.UNKNOWN

    def has(self, name: str) -> bool:
        """Truth shortcut for legacy callers; use status() to preserve UNKNOWN."""
        return self.status(name) in {CapabilityStatus.SUPPORTED, CapabilityStatus.SUPPORTED_WITH_LIMITATIONS}


@dataclass(frozen=True)
class CompatibilityResult:
    status: CompatibilityStatus
    version: CodexVersionInfo
    required_capabilities: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    app_server_available: bool | None = None
    protocol_compatible: bool | None = None
    limited_capabilities: tuple[str, ...] = ()
    unknown_capabilities: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def assess_compatibility(version: CodexVersionInfo, capabilities: CapabilitySet, *,
                         required: tuple[str, ...] = (), audited_version: tuple[int, int, int] = (0, 160, 1)) -> CompatibilityResult:
    missing = tuple(name for name in required if capabilities.status(name) == CapabilityStatus.UNSUPPORTED)
    unknown_required = tuple(name for name in required if capabilities.status(name) == CapabilityStatus.UNKNOWN)
    limited = tuple(name for name in required if capabilities.status(name) == CapabilityStatus.SUPPORTED_WITH_LIMITATIONS)
    unknown = tuple(name for name, status in _flatten_statuses(capabilities.values).items() if status == CapabilityStatus.UNKNOWN)
    if missing:
        return CompatibilityResult(CompatibilityStatus.UNSUPPORTED, version, required, missing,
                                   ("Required capability is explicitly unsupported by the observed schema.",),
                                   app_server_available=None, protocol_compatible=False,
                                   limited_capabilities=limited, unknown_capabilities=unknown)
    if unknown_required:
        return CompatibilityResult(CompatibilityStatus.UNKNOWN_NEWER_VERSION, version, required, (),
                                   ("Required capability state is UNKNOWN; no request was sent.",),
                                   app_server_available=None, protocol_compatible=None,
                                   limited_capabilities=limited, unknown_capabilities=unknown_required)
    parsed = version.parsed_cli_version
    if parsed is None:
        return CompatibilityResult(CompatibilityStatus.UNKNOWN_NEWER_VERSION, version, required, (),
                                   ("CLI version could not be parsed; capability observations are provisional.",),
                                   app_server_available=None, protocol_compatible=None,
                                   limited_capabilities=limited, unknown_capabilities=unknown)
    if parsed > audited_version:
        return CompatibilityResult(CompatibilityStatus.SUPPORTED_WITH_LIMITATIONS, version, required, (),
                                   ("Version is newer than the audited reference; required capabilities were observed locally.",),
                                   app_server_available=True, protocol_compatible=True,
                                   limited_capabilities=limited, unknown_capabilities=unknown)
    status = CompatibilityStatus.SUPPORTED_WITH_LIMITATIONS if limited or unknown else CompatibilityStatus.SUPPORTED
    return CompatibilityResult(status, version, required, (), (), app_server_available=True,
                               protocol_compatible=True, limited_capabilities=limited,
                               unknown_capabilities=unknown)


def _flatten_statuses(value: Any, prefix: str = "") -> dict[str, CapabilityStatus]:
    found: dict[str, CapabilityStatus] = {}
    if isinstance(value, Mapping):
        if "status" in value or "available" in value:
            if prefix:
                found[prefix] = CapabilitySet({prefix.split(".")[-1]: value}).status(prefix.split(".")[-1])
        else:
            for key, child in value.items():
                name = f"{prefix}.{key}" if prefix else str(key)
                found.update(_flatten_statuses(child, name))
    return found
