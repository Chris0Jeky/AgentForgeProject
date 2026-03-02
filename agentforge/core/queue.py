from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .utils import which
from .github import gh_json, gh


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    url: str
    labels: List[str]


def list_issues(*, label: str, limit: int = 20, state: str = "open") -> List[Issue]:
    """List issues by label using GitHub CLI.

    Returns basic metadata plus label names (for auto-routing).
    """
    if which("gh") is None:
        raise SystemExit("GitHub CLI 'gh' not found; install it or disable queue features.")
    j = gh_json(
        [
            "issue",
            "list",
            "--state",
            state,
            "--label",
            label,
            "--limit",
            str(limit),
            "--json",
            "number,title,url,labels",
        ]
    )
    issues: List[Issue] = []
    for it in (j or []):
        labs: List[str] = []
        for lab in (it.get("labels") or []):
            # `gh` returns labels as objects like {"name": "...", ...}
            name = (lab or {}).get("name")
            if name:
                labs.append(str(name))
        issues.append(Issue(number=int(it["number"]), title=it["title"], url=it["url"], labels=labs))
    return issues


def view_issue_body(number: int) -> str:
    j = gh_json(["issue", "view", str(number), "--json", "body"])
    return (j or {}).get("body", "") or ""


def claim_issue(*, number: int, from_label: str, to_label: str, comment: Optional[str] = None) -> None:
    # Move labels (best-effort)
    gh(["issue", "edit", str(number), "--remove-label", from_label, "--add-label", to_label])
    if comment:
        gh(["issue", "comment", str(number), "--body", comment])


def mark_done(*, number: int, in_progress_label: str, done_label: str, comment: Optional[str] = None) -> None:
    gh(["issue", "edit", str(number), "--remove-label", in_progress_label, "--add-label", done_label])
    if comment:
        gh(["issue", "comment", str(number), "--body", comment])
