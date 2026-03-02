from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from .utils import out, run

@dataclass(frozen=True)
class Finding:
    severity: str  # low|medium|high
    message: str

HIGH_RISK_FILE_PATTERNS = [
    re.compile(r"^\.github/workflows/"),
    re.compile(r"^\.git/"),
    re.compile(r"^\.ssh/"),
]

HIGH_RISK_CONTENT_PATTERNS = [
    re.compile(r"curl\s+[^\n]+\|\s*(sh|bash)", re.IGNORECASE),
    re.compile(r"wget\s+[^\n]+\|\s*(sh|bash)", re.IGNORECASE),
    re.compile(r"powershell\s+.*Invoke-WebRequest", re.IGNORECASE),
    re.compile(r"(?i)AWS_SECRET_ACCESS_KEY|GITHUB_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY"),
]

def git_diff_text(ws_path: Path, base_ref: str = "origin/main") -> str:
    # Use three-dot to diff against merge base
    return out(["git", "diff", "--patch", f"{base_ref}...HEAD"], cwd=ws_path)

def changed_files(ws_path: Path, base_ref: str = "origin/main") -> List[str]:
    txt = out(["git", "diff", "--name-only", f"{base_ref}...HEAD"], cwd=ws_path)
    return [x.strip() for x in txt.splitlines() if x.strip()]

def scan_diff(ws_path: Path, base_ref: str = "origin/main") -> List[Finding]:
    findings: List[Finding] = []
    files = changed_files(ws_path, base_ref=base_ref)
    for f in files:
        for pat in HIGH_RISK_FILE_PATTERNS:
            if pat.search(f):
                findings.append(Finding("high", f"High-risk path changed: {f}"))
                break

    diff = git_diff_text(ws_path, base_ref=base_ref)
    for pat in HIGH_RISK_CONTENT_PATTERNS:
        if pat.search(diff):
            findings.append(Finding("high", f"High-risk content pattern matched: {pat.pattern}"))

    # Medium heuristic: large diffs
    lines = diff.count("\n")
    if lines > 5000:
        findings.append(Finding("medium", f"Large diff ({lines} lines)"))

    return findings
