"""Stable exception hierarchy for callers of the bridge."""
from __future__ import annotations


class BridgeError(Exception):
    """Base class for errors callers may handle without inspecting internals."""


class ConfigurationError(BridgeError, ValueError):
    pass


class CapabilityUnavailableError(BridgeError):
    pass


class ServiceUnavailableError(BridgeError):
    """The resident service is not available to accept the operation."""


class ConflictError(BridgeError):
    """The requested operation conflicts with current or uncertain run state."""


class RunSecurityRejectedError(BridgeError):
    """The requested run violates the explicit trust/risk policy."""


class CapabilityIsolationUnavailableError(RunSecurityRejectedError):
    """The requested per-run isolation is not provided by the installed Codex surface."""


class QueueFullError(BridgeError, RuntimeError):
    pass


class ResourceUnavailableError(BridgeError):
    pass


class RunNotFoundError(BridgeError, KeyError):
    pass


class RunStateError(BridgeError):
    pass


class BackendError(BridgeError):
    pass


class AuthenticationError(BackendError):
    pass


class ProtocolError(BridgeError):
    pass


class BridgeTimeoutError(BridgeError, TimeoutError):
    pass
