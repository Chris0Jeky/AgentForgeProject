from __future__ import annotations

from dataclasses import asdict
from typing import List

from .config import Policy

def is_allowed_commenter(pol: Policy, github_login: str) -> bool:
    return github_login in (pol.allowed_comment_authors or [])

def policy_summary(pol: Policy) -> str:
    authors = ", ".join(pol.allowed_comment_authors or []) or "(none)"
    return (
        f"Policy mode: {pol.mode}\n"
        f"Allowed PR commenters: {authors}\n"
        f"Deny forks: {pol.deny_forks}\n"
        f"Auto-commit: {pol.allow_auto_commit}  Auto-push: {pol.allow_auto_push}\n"
        f"Require harness check: {pol.require_harness_check}\n"
        f"Max changed lines: {pol.max_changed_lines}"
    )
