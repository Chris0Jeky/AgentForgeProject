from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import RepoConfig, Policy
from .state import load_state, save_state, state_lock
from .workspace import list_workspaces, Workspace
from .policy import is_allowed_commenter
from .github import (
    list_open_prs,
    pr_view,
    list_issue_comments,
    post_pr_comment,
)
from .runner import run_agent_role
from .harness import run_harness_step

COMMAND_RE = re.compile(r"^/agentforge\s+(?P<cmd>\w+)(?P<rest>[\s\S]*)$", re.IGNORECASE)

def _parse_repo(cfg: RepoConfig) -> Tuple[str, str]:
    if not cfg.repo or "/" not in cfg.repo:
        raise SystemExit("GitHub repo not configured. Set `repo = \"owner/name\"` in .agentforge/config.toml")
    owner, name = cfg.repo.split("/", 1)
    return owner, name

def _branch_to_agent_task(head_ref: str) -> Optional[Tuple[str, str]]:
    # Branch format: af/<agent>/<task>
    parts = head_ref.split("/")
    if len(parts) < 3:
        return None
    if parts[0] != "af":
        return None
    agent = parts[1]
    task = "/".join(parts[2:])
    return agent, task

def _find_workspace(st_file: Path, agent: str, task: str) -> Optional[Workspace]:
    for ws in list_workspaces(st_file):
        if ws.agent == agent and ws.task == task:
            return ws
    return None

def _handle_command(root: Path, cfg: RepoConfig, pol: Policy, st_file: Path, pr_number: int, author: str, cmd: str, rest: str) -> None:
    cmd_l = cmd.lower().strip()

    if cmd_l == "help":
        post_pr_comment(pr_number,
            "AgentForge commands:\n"
            "- `/agentforge status`\n"
            "- `/agentforge review`\n"
            "- `/agentforge qa` (runs harness check)\n"
            "- `/agentforge fix` <instructions>\n"
            "- `/agentforge help`\n"
        )
        return

    if cmd_l == "status":
        post_pr_comment(pr_number, "AgentForge is alive on this host.")
        return

    info = pr_view(pr_number)
    if pol.deny_forks and info.is_cross_repo:
        post_pr_comment(pr_number, "Refusing: fork PRs are disabled by policy.")
        return

    at = _branch_to_agent_task(info.head_ref)
    if not at:
        post_pr_comment(pr_number, f"Refusing: PR head ref '{info.head_ref}' does not match af/<agent>/<task> naming.")
        return
    agent, task = at
    ws = _find_workspace(st_file, agent, task)
    if not ws:
        post_pr_comment(pr_number, f"No local workspace for {agent}:{task}. Run `agentforge spawn --agent {agent} --task {task}` on the host.")
        return

    if cmd_l == "review":
        post_pr_comment(pr_number, f"Running review agent for {agent}:{task} ...")
        try:
            run_agent_role(root, cfg, pol, ws, provider=cfg.default_provider, role="review", prompt=rest.strip() or "", auto_commit=False, auto_push=False)
            post_pr_comment(pr_number, "Review finished. (Check local logs/terminal output for details.)")
        except Exception as e:
            post_pr_comment(pr_number, f"Review failed: {e}")
        return

    if cmd_l == "qa":
        post_pr_comment(pr_number, f"Running harness check for {agent}:{task} ...")
        try:
            run_harness_step(root, cfg, ws, step="check", extra_env=None)
            post_pr_comment(pr_number, "Harness check: PASS")
        except Exception as e:
            post_pr_comment(pr_number, f"Harness check: FAIL\n{e}")
        return

    if cmd_l == "fix":
        instructions = rest.strip()
        if not instructions:
            post_pr_comment(pr_number, "Usage: `/agentforge fix` then include requested changes in the same comment body.")
            return
        post_pr_comment(pr_number, f"Running fix agent for {agent}:{task} ...")
        try:
            run_agent_role(root, cfg, pol, ws, provider=cfg.default_provider, role="fix", prompt=instructions, auto_commit=True, auto_push=True)
            post_pr_comment(pr_number, "Fix finished and pushed (if auto-push is enabled)." )
        except Exception as e:
            post_pr_comment(pr_number, f"Fix failed: {e}")
        return

    post_pr_comment(pr_number, f"Unknown command: `{cmd}`. Try `/agentforge help`.")

def run_daemon_once(root: Path, cfg: RepoConfig, pol: Policy, st_file: Path) -> None:
    owner, name = _parse_repo(cfg)

    with state_lock(st_file):
        st = load_state(st_file)
        st.setdefault("prs", {})
        save_state(st_file, st)

    prs = list_open_prs()
    for pr in prs:
        pr_number = int(pr["number"])
        info = pr_view(pr_number)
        if pol.deny_forks and info.is_cross_repo:
            continue

        comments = list_issue_comments(owner, name, pr_number)

        with state_lock(st_file):
            st = load_state(st_file)
            last_id = int(st.get("prs", {}).get(str(pr_number), {}).get("last_comment_id", 0))

        new_cmds: List[Tuple[int, str, str, str]] = []
        for c in comments:
            cid = int(c["id"])
            if cid <= last_id:
                continue
            body = (c.get("body") or "").strip()
            m = COMMAND_RE.match(body)
            if not m:
                continue
            author = c["user"]["login"]
            cmd = m.group("cmd")
            rest = m.group("rest") or ""
            new_cmds.append((cid, author, cmd, rest))

        if not new_cmds:
            continue

        # update last seen immediately
        max_id = max(cid for cid, _, _, _ in new_cmds)
        with state_lock(st_file):
            st = load_state(st_file)
            st.setdefault("prs", {}).setdefault(str(pr_number), {})["last_comment_id"] = max_id
            save_state(st_file, st)

        for cid, author, cmd, rest in new_cmds:
            if not is_allowed_commenter(pol, author):
                post_pr_comment(pr_number, f"Refusing command from @{author}: not allowlisted.")
                continue
            try:
                _handle_command(root, cfg, pol, st_file, pr_number, author, cmd, rest)
            except Exception as e:
                post_pr_comment(pr_number, f"AgentForge error handling command: {e}")


    # Sticky lock maintenance (best-effort). This renews sticky locks and can
    # auto-release them when their linked PR is merged/closed.
    try:
        from .lock_maintenance import maybe_maintain_sticky_locks
        maybe_maintain_sticky_locks(root, cfg, st_file)
    except Exception:
        pass

def run_daemon_forever(root: Path, cfg: RepoConfig, pol: Policy, st_file: Path) -> None:
    while True:
        run_daemon_once(root, cfg, pol, st_file)
        time.sleep(cfg.poll_interval_sec)
