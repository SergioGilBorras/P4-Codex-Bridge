"""Stable consumer API for P4-Codex-Bridge.

Runtime manager, SQLite, scheduler, process and app-server transport modules are
implementation details. Importing the package root performs no runtime startup.
"""
from importlib import import_module

__version__ = "1.1.0"

_EXPORTS = {
    "CodexBridge": ("client", "CodexBridge"),
    "CodexServiceClient": ("service_client", "CodexServiceClient"),
    "ExecRunSubmission": ("service_client", "ExecRunSubmission"),
    "CreateThreadRequest": ("service_client", "CreateThreadRequest"),
    "StartTurnRequest": ("service_client", "StartTurnRequest"),
    "CommandResult": ("service_client", "CommandResult"),
    "CodexPermissions": ("permissions", "CodexPermissions"),
    "RunSecurityPolicy": ("security", "RunSecurityPolicy"),
    "ProjectTrust": ("security", "ProjectTrust"),
    "SecurityDecision": ("security", "SecurityDecision"),
    "SecurityDecisionResult": ("security", "SecurityDecisionResult"),
    "validate_run_security": ("security", "validate_run_security"),
    "CodexVersionInfo": ("compatibility", "CodexVersionInfo"),
    "CapabilitySet": ("compatibility", "CapabilitySet"),
    "CompatibilityResult": ("compatibility", "CompatibilityResult"),
    "CompatibilityStatus": ("compatibility", "CompatibilityStatus"),
    "assess_compatibility": ("compatibility", "assess_compatibility"),
    "CapabilityStatus": ("compatibility", "CapabilityStatus"),
    "AppServerCapabilityStatus": ("app_server_capabilities", "AppServerCapabilityStatus"),
    "AppServerCapabilitySet": ("app_server_capabilities", "AppServerCapabilitySet"),
    "ApprovalRequest": ("events", "ApprovalRequest"),
    "ApprovalError": ("events", "ApprovalError"),
    "ApprovalTimeoutError": ("events", "ApprovalTimeoutError"),
    "ApprovalRejectedError": ("events", "ApprovalRejectedError"),
    "CodexEvent": ("events", "CodexEvent"),
    "EventStreamError": ("events", "EventStreamError"),
    "EventDecodeError": ("events", "EventDecodeError"),
    "ToolEventError": ("events", "ToolEventError"),
    "RunResult": ("models", "RunResult"),
    "BridgeRun": ("models", "BridgeRun"),
    "RunStatus": ("models", "RunStatus"),
    "ConfigPolicy": ("models", "ConfigPolicy"),
    "SandboxMode": ("models", "SandboxMode"),
    "ApprovalPolicy": ("models", "ApprovalPolicy"),
    "ApprovalHandlingPolicy": ("models", "ApprovalHandlingPolicy"),
    "AppServerApprovalPolicy": ("models", "AppServerApprovalPolicy"),
    "CodexTurn": ("app_server", "CodexTurn"),
    "BridgeError": ("errors", "BridgeError"),
    "ConfigurationError": ("errors", "ConfigurationError"),
    "CapabilityUnavailableError": ("errors", "CapabilityUnavailableError"),
    "ServiceUnavailableError": ("errors", "ServiceUnavailableError"),
    "ConflictError": ("errors", "ConflictError"),
    "RunSecurityRejectedError": ("errors", "RunSecurityRejectedError"),
    "CapabilityIsolationUnavailableError": ("errors", "CapabilityIsolationUnavailableError"),
    "QueueFullError": ("errors", "QueueFullError"),
    "ResourceUnavailableError": ("errors", "ResourceUnavailableError"),
    "RunNotFoundError": ("errors", "RunNotFoundError"),
    "RunStateError": ("errors", "RunStateError"),
    "BackendError": ("errors", "BackendError"),
    "AuthenticationError": ("errors", "AuthenticationError"),
    "ProtocolError": ("errors", "ProtocolError"),
    "BridgeTimeoutError": ("errors", "BridgeTimeoutError"),
}

__all__ = sorted({"__version__", *_EXPORTS})


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(f".{module_name}", __name__), attribute)
    globals()[name] = value
    return value
