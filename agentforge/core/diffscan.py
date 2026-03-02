from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .utils import out

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

def numstat_total_changed(ws_path: Path, base_ref: str = "origin/main") -> int:
    """Total changed lines (added + deleted) from git numstat."""
    txt = out(["git", "diff", "--numstat", f"{base_ref}...HEAD"], cwd=ws_path)
    total = 0
    for line in txt.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, d, _ = parts[0], parts[1], parts[2]
        # '-' indicates binary
        if a == "-" or d == "-":
            return 10**9
        try:
            total += int(a) + int(d)
        except ValueError:
            continue
    return total

def scan_diff_text(*, diff_text: str, changed_files: List[str]) -> List[Finding]:
    findings: List[Finding] = []
    for f in changed_files:
        for pat in HIGH_RISK_FILE_PATTERNS:
            if pat.search(f):
                findings.append(Finding("high", f"High-risk path changed: {f}"))
                break
    for pat in HIGH_RISK_CONTENT_PATTERNS:
        if pat.search(diff_text):
            findings.append(Finding("high", f"High-risk content pattern matched: {pat.pattern}"))
    lines = diff_text.count("\n")
    if lines > 5000:
        findings.append(Finding("medium", f"Large diff ({lines} lines)"))
    return findings

def scan_diff(ws_path: Path, base_ref: str = "origin/main") -> List[Finding]:
    files = changed_files(ws_path, base_ref=base_ref)
    diff = git_diff_text(ws_path, base_ref=base_ref)
    return scan_diff_text(diff_text=diff, changed_files=files)
