from __future__ import annotations

import json
import re
from pathlib import Path

from .config import RepoConfig, Policy
from .policy import is_allowed_commenter
from .daemon import _process_comments, _parse_repo
from .github import list_issue_comments

COMMAND_RE = re.compile(r"^/agentforge\s+(?P<cmd>\w+)(?P<rest>[\s\S]*)$", re.IGNORECASE)

def handle_github_event_file(root: Path, cfg: RepoConfig, pol: Policy, st_file: Path, event_path: Path) -> None:
    payload = json.loads(event_path.read_text(encoding="utf-8"))

    # Handle only issue_comment created events
    if payload.get("action") != "created":
        return
    comment = payload.get("comment") or {}
    issue = payload.get("issue") or {}

    # PR comments have issue.pull_request present
    if "pull_request" not in issue:
        return

    body = (comment.get("body") or "").strip()
    m = COMMAND_RE.match(body)
    if not m:
        return

    author = (comment.get("user") or {}).get("login") or ""
    if not is_allowed_commenter(pol, author):
        # refuse silently; up to you if you want to comment
        return

    pr_number = int(issue.get("number"))
    comment_id = int(comment.get("id") or 0)

    owner, name = _parse_repo(cfg)
    comments = list_issue_comments(owner, name, pr_number)
    if not any(int(c["id"]) == comment_id for c in comments):
        comments.append(comment)
    _process_comments(root, cfg, pol, st_file, pr_number, comments)
