from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .config import RepoConfig, Policy
from .preflight import check_tools, print_preflight
from .queue import list_issues, view_issue_body, claim_issue
from .workspace import spawn_workspace, list_workspaces
from .runner import run_agent_role
from .pr import create_pr
from .guardrails import sanitize_id
from .utils import out, run, which
from .state import state_paths

@dataclass(frozen=True)
class BootstrapPlanItem:
    agent: str
    task: str
    issue_number: int
    issue_title: str
    issue_url: str

def _default_agents(n: int) -> List[str]:
    return [f"a{i}" for i in range(1, n+1)]

def build_plan_from_queue(cfg: RepoConfig, *, agents: List[str], take: int, label: str) -> List[BootstrapPlanItem]:
    issues = list_issues(label=label, limit=take)
    plan: List[BootstrapPlanItem] = []
    if not issues:
        return plan
    if not agents:
        agents = _default_agents(min(take, 3))
    for i, iss in enumerate(issues[:take]):
        agent = agents[i % len(agents)]
        task = f"issue-{iss.number}"
        plan.append(BootstrapPlanItem(agent=agent, task=task, issue_number=iss.number, issue_title=iss.title, issue_url=iss.url))
    return plan

def run_bootstrap(
    root: Path,
    cfg: RepoConfig,
    pol: Policy,
    *,
    agents: List[str],
    take: int,
    fast: bool,
    claim: bool,
    create_prs: bool,
    draft_prs: bool,
    run_daemon: bool,
) -> None:
    # Preflight
    require_gh = bool(cfg.repo) and (claim or create_prs or run_daemon)
    require_codex = (cfg.default_provider == "codex_cli") and fast
    status = check_tools(require_gh=require_gh, require_docker=False, require_codex=require_codex)
    print_preflight(status)

    st_file, _ = state_paths(root, cfg)

    plan = build_plan_from_queue(cfg, agents=agents, take=take, label=cfg.queue_label)
    if not plan:
        print(f"No issues found with label '{cfg.queue_label}'. Nothing to do.")
        return

    print("Bootstrap plan:")
    for it in plan:
        print(f"- {it.agent}: {it.task}  (#{it.issue_number} {it.issue_title})")

    # Execute plan
    for it in plan:
        # If workspace already exists, skip spawn
        existing = {(ws.agent, ws.task) for ws in list_workspaces(st_file)}
        if (it.agent, it.task) not in existing:
            ws = spawn_workspace(root, cfg, pol, st_file, agent=it.agent, task=it.task, base_ref=cfg.default_base_ref)
        else:
            ws = [w for w in list_workspaces(st_file) if w.agent == it.agent and w.task == it.task][0]

        if claim:
            msg = f"Claimed by AgentForge agent '{it.agent}' on host at {time.strftime('%Y-%m-%d %H:%M:%S')}."
            claim_issue(number=it.issue_number, from_label=cfg.queue_label, to_label=cfg.in_progress_label, comment=msg)

        if fast:
            body = view_issue_body(it.issue_number)
            prompt = (
                f"Implement GitHub issue #{it.issue_number}: {it.issue_title}\n"
                f"Issue URL: {it.issue_url}\n\n"
                f"Issue body:\n{body}\n"
            )
            # implement role: will run harness checks + commit/push if enabled by args and policy
            run_agent_role(root, cfg, pol, ws, provider=cfg.default_provider, role="implement", prompt=prompt, auto_commit=True, auto_push=True)

            if create_prs:
                pr_title = f"[{it.agent}] {it.issue_title} (#{it.issue_number})"
                pr_body = (
                    f"Automated by AgentForge.\n\n"
                    f"Closes #{it.issue_number}\n\n"
                    f"Agent: {it.agent}\nTask: {it.task}\n"
                )
                pr = create_pr(ws_path=Path(ws.path), title=pr_title, body=pr_body, base=cfg.default_base_branch, head=ws.branch, draft=draft_prs)
                print(f"Created PR: {pr.url}")

    if run_daemon:
        from .daemon import run_daemon_forever
        run_daemon_forever(root, cfg, pol, st_file)
