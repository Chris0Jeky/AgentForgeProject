from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .utils import which, out, run
from .github import gh_json, gh

@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    url: str

def list_issues(*, label: str, limit: int=20, state: str="open") -> List[Issue]:
    if which("gh") is None:
        raise SystemExit("GitHub CLI 'gh' not found; install it or disable queue features.")
    j = gh_json(["issue", "list", "--state", state, "--label", label, "--limit", str(limit), "--json", "number,title,url"])
    issues: List[Issue] = []
    for it in (j or []):
        issues.append(Issue(number=int(it["number"]), title=it["title"], url=it["url"]))
    return issues

def view_issue_body(number: int) -> str:
    j = gh_json(["issue", "view", str(number), "--json", "body"])
    return (j or {}).get("body", "") or ""

def claim_issue(*, number: int, from_label: str, to_label: str, comment: Optional[str]=None) -> None:
    # Move labels (best-effort)
    gh(["issue", "edit", str(number), "--remove-label", from_label, "--add-label", to_label])
    if comment:
        gh(["issue", "comment", str(number), "--body", comment])

def mark_done(*, number: int, in_progress_label: str, done_label: str, comment: Optional[str]=None) -> None:
    gh(["issue", "edit", str(number), "--remove-label", in_progress_label, "--add-label", done_label])
    if comment:
        gh(["issue", "comment", str(number), "--body", comment])
