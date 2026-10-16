"""Explicit trust and risk policy for Codex runs.

Codex does not expose a verified per-run MCP allowlist. This module therefore
never treats sandbox permissions as a control over external MCP side effects.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .errors import CapabilityIsolationUnavailableError, RunSecurityRejectedError


class ProjectTrust(str, Enum):
    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"
    UNKNOWN = "UNKNOWN"


class SecurityDecision(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_WITH_WARNING = "ALLOW_WITH_WARNING"
    REJECT = "REJECT"


@dataclass(frozen=True)
class RunSecurityPolicy:
    """Caller-declared project/config/MCP risk policy; not a Codex permission."""

    project_trust: ProjectTrust = ProjectTrust.UNKNOWN
    allow_project_config: bool = False
    allow_agents: bool = False
    allow_skills: bool = False
    allow_external_mcps: bool = False
    allow_side_effect_mcps: bool = False
    require_mcp_isolation: bool = False
    explicit_risk_acknowledgement: bool = False
    policy_id: str = "restricted-default"
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_trust", ProjectTrust(self.project_trust))
        for name in ("allow_project_config", "allow_agents", "allow_skills", "allow_external_mcps",
                     "allow_side_effect_mcps", "require_mcp_isolation", "explicit_risk_acknowledgement"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if not self.policy_id or len(self.policy_id) > 80:
            raise ValueError("policy_id must contain 1-80 characters")
        if self.version != 1:
            raise ValueError("unsupported security policy version")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["project_trust"] = self.project_trust.value
        return data

    @classmethod
    def from_dict(cls, value: Any) -> "RunSecurityPolicy":
        if not isinstance(value, dict):
            raise ValueError("security_policy must be an object")
        allowed = {field for field in cls.__dataclass_fields__}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("unknown security policy fields: " + ", ".join(sorted(unknown)))
        return cls(**value)


@dataclass(frozen=True)
class SecurityDecisionResult:
    decision: SecurityDecision
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    policy_id: str = "restricted-default"

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision.value, "reasons": list(self.reasons),
                "warnings": list(self.warnings), "policy_id": self.policy_id}


def validate_run_security(policy: RunSecurityPolicy | None, *, backend: str,
                          config_policy: str, cwd: str | Path | None = None,
                          effective_mcp_state: str = "UNKNOWN") -> SecurityDecisionResult:
    """Evaluate known risk; UNKNOWN is never interpreted as absence.

    `effective_mcp_state` is intentionally bridge-owned. The public caller cannot
    assert that a child has no MCPs; absent a verified receipt it remains UNKNOWN.
    """
    policy = policy or RunSecurityPolicy()
    state = effective_mcp_state.upper()
    if state not in {"UNKNOWN", "PRESENT", "NONE_CONFIRMED"}:
        raise ValueError("invalid effective MCP state")
    reasons: list[str] = []
    warnings: list[str] = []
    project_config_found = False
    agents_found = False
    if cwd is not None:
        root = Path(cwd).resolve()
        project_root = next((parent for parent in (root, *root.parents) if (parent / ".git").exists()), root)
        for parent in (root, *root.parents):
            if parent == project_root.parent:
                break
            project_config_found |= (parent / ".codex" / "config.toml").is_file()
            agents_found |= (parent / "AGENTS.md").is_file()
    if project_config_found and not policy.allow_project_config:
        reasons.append("project_config_present_but_not_allowed")
    if agents_found and not policy.allow_agents:
        reasons.append("agents_file_present_but_not_allowed")
    if (project_config_found or agents_found) and policy.project_trust != ProjectTrust.TRUSTED:
        reasons.append("project_context_requires_trusted_project")
    if policy.require_mcp_isolation:
        raise CapabilityIsolationUnavailableError(
            "MCP per-run isolation is not verified by this Codex version; the run was rejected."
        )
    if policy.project_trust != ProjectTrust.TRUSTED and any((policy.allow_project_config, policy.allow_agents, policy.allow_skills)):
        reasons.append("project_context_requires_trusted_project")
    if policy.allow_side_effect_mcps and not policy.allow_external_mcps:
        reasons.append("side_effect_mcps_require_external_mcp_opt_in")
    if policy.allow_external_mcps or policy.allow_side_effect_mcps:
        if policy.project_trust != ProjectTrust.TRUSTED:
            reasons.append("external_mcp_risk_requires_trusted_project")
        if not policy.explicit_risk_acknowledgement:
            reasons.append("external_mcp_risk_acknowledgement_required")
        if not policy.allow_side_effect_mcps:
            reasons.append("Codex cannot filter MCP tools by side-effect category per run")
        else:
            warnings.append("external MCP tools may have side effects; Codex does not provide verified per-run filtering")
    elif state != "NONE_CONFIRMED":
        reasons.append("effective_external_mcp_set_unknown")
    if reasons:
        raise RunSecurityRejectedError("Run rejected by security policy: " + "; ".join(reasons))
    decision = SecurityDecision.ALLOW_WITH_WARNING if warnings else SecurityDecision.ALLOW
    return SecurityDecisionResult(decision, warnings=tuple(warnings), policy_id=policy.policy_id)
