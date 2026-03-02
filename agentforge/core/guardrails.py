from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, List, Optional

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

def sanitize_id(s: str) -> str:
    """Sanitize an identifier for use in folder names, docker compose project names, and branch segments."""
    s = s.strip().replace(" ", "-")
    s = _SAFE_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-") or "id"

def matches_any_glob(path: str, globs: Iterable[str]) -> bool:
    # Normalize to posix for stable matching across OS
    p = PurePosixPath(path.replace("\\", "/"))
    for g in globs:
        g = (g or "").strip()
        if not g:
            continue
        # PurePosixPath.match supports ** semantics
        try:
            if p.match(g):
                return True
        except Exception:
            # fallback: fnmatch
            if fnmatch.fnmatch(str(p), g):
                return True
    return False

@dataclass(frozen=True)
class GuardrailFinding:
    severity: str  # warn|block
    message: str

def evaluate_policy_globs(*, changed_files: List[str], forbid_globs: List[str], protect_globs: List[str], protect_behavior: str) -> List[GuardrailFinding]:
    findings: List[GuardrailFinding] = []
    for f in changed_files:
        if matches_any_glob(f, forbid_globs):
            findings.append(GuardrailFinding("block", f"Forbidden path changed by automation: {f}"))
        if matches_any_glob(f, protect_globs):
            if protect_behavior.lower() == "halt":
                findings.append(GuardrailFinding("block", f"Protected path changed (halt policy): {f}"))
            else:
                findings.append(GuardrailFinding("warn", f"Protected path changed: {f}"))
    return findings
