from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .utils import which, run, out
from .github import gh_json, gh

@dataclass(frozen=True)
class PrCreated:
    number: int
    url: str

def pr_exists_for_branch(branch: str) -> bool:
    # `gh pr list --head` can return empty
    j = gh_json(["pr", "list", "--state", "open", "--head", branch, "--json", "number"])
    return bool(j)

def create_pr(*, ws_path: Path, title: str, body: str, base: str, head: Optional[str]=None, draft: bool=True) -> PrCreated:
    if which("gh") is None:
        raise SystemExit("GitHub CLI 'gh' not found; install it or disable PR features.")
    args = ["pr", "create", "--title", title, "--body", body, "--base", base]
    if head:
        args += ["--head", head]
    if draft:
        args.append("--draft")
    # Run in workspace directory so gh can infer repo and branch
    run(["gh"] + args, cwd=ws_path, capture=False)
    # Extract created PR info by querying current branch
    j = gh_json(["pr", "view", "--json", "number,url"], cwd=ws_path)
    return PrCreated(number=int(j["number"]), url=j["url"])
