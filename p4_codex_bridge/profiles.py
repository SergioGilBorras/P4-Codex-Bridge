from __future__ import annotations

from dataclasses import dataclass

from .models import ApprovalPolicy, SandboxMode
from .permissions import CodexPermissions


@dataclass(frozen=True)
class Profile:
    name: str
    permissions: CodexPermissions
    timeout_seconds: float = 300
    config_policy: str = "project"
    status: str = "IMPLEMENTED"


PROFILES = {
    "analysis": Profile(
        name="analysis",
        permissions=CodexPermissions(SandboxMode.READ_ONLY, ApprovalPolicy.NEVER),
        config_policy="isolated",
    ),
    "planning": Profile("planning", CodexPermissions(), status="PLANNED"),
    "implementation": Profile("implementation", CodexPermissions(SandboxMode.WORKSPACE_WRITE, ApprovalPolicy.ON_REQUEST), status="PLANNED"),
    "validation": Profile("validation", CodexPermissions(), status="PLANNED"),
    "documentation": Profile("documentation", CodexPermissions(), status="PLANNED"),
}


def get_profile(name: str) -> Profile:
    profile = PROFILES.get(name)
    if profile is None:
        raise ValueError(f"unknown profile: {name}")
    if profile.status != "IMPLEMENTED":
        raise ValueError(f"profile is planned but not implemented: {name}")
    return profile
