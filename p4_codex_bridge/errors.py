"""Stable exception hierarchy for callers of the bridge."""
from __future__ import annotations


class BridgeError(Exception):
    """Base class for errors callers may handle without inspecting internals."""


class ConfigurationError(BridgeError, ValueError):
    pass


class CapabilityUnavailableError(BridgeError):
    pass


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
