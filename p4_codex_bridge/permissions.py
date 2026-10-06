from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import ApprovalPolicy, SandboxMode


@dataclass(frozen=True)
class CodexPermissions:
    """Codex sandbox controls verified for the selected backend."""

    sandbox: SandboxMode = SandboxMode.READ_ONLY
    approval_policy: ApprovalPolicy = ApprovalPolicy.NEVER
    writable_roots: tuple[str | Path, ...] = ()
    network_access: bool | None = None


@dataclass(frozen=True)
class CwdPolicy:
    """Bridge-side cwd allowlist; Codex sandbox controls remain separate."""

    allowed_roots: tuple[Path, ...] = ()

    def resolve(self, cwd: str | Path) -> Path:
        path = Path(cwd).expanduser()
        if not path.is_absolute():
            raise ValueError("cwd must be an absolute path")
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("cwd must be an existing directory") from exc
        if not resolved.is_dir():
            raise ValueError("cwd must be an existing directory")
        roots = tuple(root.expanduser().resolve(strict=True) for root in self.allowed_roots)
        if roots and not any(resolved == root or root in resolved.parents for root in roots):
            raise ValueError("cwd is outside configured allowed roots")
        return resolved

    def resolve_writable_roots(self, roots: tuple[str | Path, ...] | list[str | Path], *, cwd: Path) -> tuple[Path, ...]:
        resolved: list[Path] = []
        allowed = tuple(root.expanduser().resolve(strict=True) for root in self.allowed_roots) or (cwd,)
        seen: set[str] = set()
        for root in roots:
            path = Path(root).expanduser()
            if not path.is_absolute():
                raise ValueError("writable roots must be absolute paths")
            try:
                canonical = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError("writable roots must be existing directories") from exc
            if not canonical.is_dir():
                raise ValueError("writable roots must be existing directories")
            key = str(canonical).casefold()
            if key in seen:
                raise ValueError("duplicate writable root")
            seen.add(key)
            if not any(canonical == base or base in canonical.parents for base in allowed):
                raise ValueError("writable root is outside configured allowed roots")
            resolved.append(canonical)
        return tuple(resolved)
