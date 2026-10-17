from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .file_mutex import file_mutex
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

def _handle_command(root: Path, cfg: RepoConfig, pol: Policy, st_file: Path, pr_number: int, author: str, cmd: str, rest: str) -> str:
    cmd_l = cmd.lower().strip()
    if cmd_l == "help":
        return "AgentForge commands: `/agentforge status`, `review`, `qa`, `fix <instructions>`, `help`."
    if cmd_l == "status":
        return "AgentForge is alive on this host."

    info = pr_view(pr_number)
    if pol.deny_forks and info.is_cross_repo:
        return "Refusing: fork PRs are disabled by policy."
    at = _branch_to_agent_task(info.head_ref)
    if not at:
        return f"Refusing: PR head ref '{info.head_ref}' does not match af/<agent>/<task> naming."
    agent, task = at
    ws = _find_workspace(st_file, agent, task)
    if not ws:
        return f"No local workspace for {agent}:{task}. Run `agentforge spawn --agent {agent} --task {task}` on the host."

    if cmd_l == "review":
        run_agent_role(root, cfg, pol, ws, provider=cfg.default_provider, role="review", prompt=rest.strip() or "", auto_commit=False, auto_push=False)
        return "Review finished. (Check local logs/terminal output for details.)"
    if cmd_l == "qa":
        if not run_harness_step(root, cfg, ws, step="check", extra_env=None):
            raise RuntimeError("Harness check: FAIL")
        return "Harness check: PASS"
    if cmd_l == "fix":
        if not rest.strip():
            return "Usage: `/agentforge fix` then include requested changes in the same comment body."
        run_agent_role(root, cfg, pol, ws, provider=cfg.default_provider, role="fix", prompt=rest.strip(), auto_commit=True, auto_push=True)
        return "Fix finished and pushed (if auto-push is enabled)."
    return f"Unknown command: `{cmd}`. Try `/agentforge help`."


def _process_comments(root: Path, cfg: RepoConfig, pol: Policy, st_file: Path,
                      pr_number: int, comments: List[dict]) -> None:
    with file_mutex(st_file.with_name(f"commands-pr-{pr_number}.mutex"), timeout=0):
        _process_comments_locked(root, cfg, pol, st_file, pr_number, comments)


def _process_comments_locked(root: Path, cfg: RepoConfig, pol: Policy, st_file: Path,
                      pr_number: int, comments: List[dict]) -> None:
    with state_lock(st_file):
        st = load_state(st_file)
        pr = st.setdefault("prs", {}).setdefault(str(pr_number), {})
        receipts = pr.setdefault("commands", {})
        last_id = int(pr.get("last_comment_id", 0))
        for c in comments:
            cid = int(c["id"])
            m = COMMAND_RE.match((c.get("body") or "").strip())
            if cid > last_id and m:
                receipts.setdefault(str(cid), {"state": "observed", "author": c["user"]["login"],
                                               "cmd": m.group("cmd"), "rest": m.group("rest") or ""})
        pending = sorted(int(cid) for cid in receipts if int(cid) > last_id)
        save_state(st_file, st)

    for cid in pending:
        marker = f"<!-- agentforge-command:{cid} -->"
        with state_lock(st_file):
            st = load_state(st_file)
            pr = st["prs"][str(pr_number)]
            receipt = pr["commands"][str(cid)]
            phase = receipt["state"]
            if phase == "executing":
                receipt.update(state="reconciliation_required", response=
                               "Execution was interrupted; reconcile workspace, branch and PR before retrying.")
            dispatch = phase in {"observed", "admitted"}
            if dispatch:
                receipt["state"] = "admitted"
                save_state(st_file, st)
                receipt["state"] = "executing"
            save_state(st_file, st)
            command = dict(receipt)

        if dispatch:
            try:
                if not is_allowed_commenter(pol, command["author"]):
                    response = f"Refusing command from @{command['author']}: not allowlisted."
                else:
                    response = _handle_command(root, cfg, pol, st_file, pr_number,
                                               command["author"], command["cmd"], command["rest"])
                outcome = "completed"
            except (Exception, SystemExit) as e:
                response = f"{command['cmd'].capitalize()} failed: {str(e)[:2000]}. Reconcile workspace, branch and PR before retrying."
                outcome = "reconciliation_required"
            with state_lock(st_file):
                st = load_state(st_file)
                receipt = st["prs"][str(pr_number)]["commands"][str(cid)]
                receipt.update(state=outcome, response=response)
                save_state(st_file, st)

        with state_lock(st_file):
            st = load_state(st_file)
            receipt = dict(st["prs"][str(pr_number)]["commands"][str(cid)])
        if not receipt.get("delivered"):
            try:
                if not any(marker in (c.get("body") or "") for c in comments):
                    post_pr_comment(pr_number, f"AgentForge response to comment #{cid}:\n{receipt['response']}\n{marker}")
            except Exception as e:
                with state_lock(st_file):
                    st = load_state(st_file)
                    st["prs"][str(pr_number)]["commands"][str(cid)]["delivery_error"] = str(e)[:2000]
                    save_state(st_file, st)
                break
            with state_lock(st_file):
                st = load_state(st_file)
                st["prs"][str(pr_number)]["commands"][str(cid)]["delivered"] = True
                save_state(st_file, st)
        if receipt["state"] == "reconciliation_required":
            break
        with state_lock(st_file):
            st = load_state(st_file)
            st["prs"][str(pr_number)]["last_comment_id"] = cid
            save_state(st_file, st)


def run_daemon_once(root: Path, cfg: RepoConfig, pol: Policy, st_file: Path) -> None:
    owner, name = _parse_repo(cfg)

    with state_lock(st_file):
        st = load_state(st_file)
        st.setdefault("prs", {})
        save_state(st_file, st)

    for pr in list_open_prs():
        pr_number = int(pr["number"])
        try:
            info = pr_view(pr_number)
            if pol.deny_forks and info.is_cross_repo:
                continue
            comments = list_issue_comments(owner, name, pr_number)
            _process_comments(root, cfg, pol, st_file, pr_number, comments)
        except (Exception, SystemExit) as e:
            with state_lock(st_file):
                st = load_state(st_file)
                st.setdefault("prs", {}).setdefault(str(pr_number), {})["error"] = str(e)[:2000]
                save_state(st_file, st)

    # Sticky lock maintenance (best-effort). This renews sticky locks and can
    # auto-release them when their linked PR is merged/closed.
    try:
        from .lock_maintenance import maybe_maintain_sticky_locks
        maybe_maintain_sticky_locks(root, cfg, st_file)
    except Exception:
        pass

def run_daemon_forever(root: Path, cfg: RepoConfig, pol: Policy, st_file: Path) -> None:
    while True:
        try:
            run_daemon_once(root, cfg, pol, st_file)
        except (Exception, SystemExit) as e:
            print(f"AgentForge poll failed: {str(e)[:2000]}")
        time.sleep(cfg.poll_interval_sec)
