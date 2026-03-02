from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import which, out

class GhMissing(RuntimeError):
    pass

def _ensure_gh() -> None:
    if which("gh") is None:
        raise GhMissing("GitHub CLI 'gh' not found on PATH")

def gh_json(args: List[str], *, cwd: Optional[Path]=None) -> Any:
    _ensure_gh()
    txt = out(["gh"] + args, cwd=cwd)
    return json.loads(txt) if txt else None

def gh(args: List[str], *, cwd: Optional[Path]=None) -> str:
    _ensure_gh()
    return out(["gh"] + args, cwd=cwd)

@dataclass(frozen=True)
class PrInfo:
    number: int
    head_ref: str
    url: str
    is_cross_repo: bool

def list_open_prs() -> List[Dict[str, Any]]:
    return gh_json(["pr", "list", "--state", "open", "--json", "number,title,headRefName"]) or []

def pr_view(pr_number: int) -> PrInfo:
    j = gh_json(["pr", "view", str(pr_number), "--json", "number,headRefName,url,isCrossRepository"]) or {}
    return PrInfo(
        number=int(j["number"]),
        head_ref=j["headRefName"],
        url=j["url"],
        is_cross_repo=bool(j.get("isCrossRepository", False)),
    )

def list_issue_comments(owner: str, repo: str, issue_number: int) -> List[Dict[str, Any]]:
    # PR conversation comments are issue comments on the underlying issue
    return gh_json(["api", f"repos/{owner}/{repo}/issues/{issue_number}/comments", "--paginate"]) or []

def post_pr_comment(pr_number: int, body: str) -> None:
    gh(["pr", "comment", str(pr_number), "--body", body])
