from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .config import RepoConfig, Policy
from .policy import is_allowed_commenter
from .daemon import _handle_command  # reuse
from .state import load_state, save_state, state_lock

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
    cmd = m.group("cmd")
    rest = m.group("rest") or ""
    comment_id = int(comment.get("id") or 0)

    # Update last seen
    with state_lock(st_file):
        st = load_state(st_file)
        st.setdefault("prs", {}).setdefault(str(pr_number), {})["last_comment_id"] = max(
            int(st.get("prs", {}).get(str(pr_number), {}).get("last_comment_id", 0)),
            comment_id
        )
        save_state(st_file, st)

    _handle_command(root, cfg, pol, st_file, pr_number, author, cmd, rest)
