from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from .config import RepoConfig, Policy
from .preflight import check_tools, print_preflight
from .queue import list_issues, view_issue_body, claim_issue
from .workspace import spawn_workspace, list_workspaces
from .workflow import run_workflow
from .locks import load_lock_groups, select_lock_group_for_issue
from .utils import out, run, which
from .state import state_paths


@dataclass(frozen=True)
class BootstrapPlanItem:
    agent: str
    task: str
    issue_number: int
    issue_title: str
    issue_url: str
    issue_labels: List[str]
    lock_group: str
    workflow: str


def _default_agents(n: int) -> List[str]:
    return [f"a{i}" for i in range(1, n + 1)]


def build_plan_from_queue(
    root: Path,
    cfg: RepoConfig,
    *,
    agents: List[str],
    take: int,
    label: str,
    workflow_override: Optional[str] = None,
    prefer_unique_locks: bool = True,
) -> List[BootstrapPlanItem]:
    issues = list_issues(label=label, limit=max(take * 4, take), state="open")
    if not issues:
        return []

    if not agents:
        agents = _default_agents(min(take, 3))

    lock_groups = load_lock_groups(root)

    def plan_item(i, iss) -> BootstrapPlanItem:
        spec = select_lock_group_for_issue(
            lock_groups,
            issue_labels=iss.labels,
            issue_title=iss.title,
            strategy=cfg.auto_lock_strategy,
        )
        lock_group = (spec.name if spec else None) or (lock_groups.default_group().name if lock_groups.default_group() else "repo")
        workflow = workflow_override or (spec.workflow if spec and spec.workflow else cfg.default_workflow)
        agent = agents[i % len(agents)]
        task = f"issue-{iss.number}"
        return BootstrapPlanItem(
            agent=agent,
            task=task,
            issue_number=iss.number,
            issue_title=iss.title,
            issue_url=iss.url,
            issue_labels=list(iss.labels or []),
            lock_group=lock_group,
            workflow=workflow,
        )

    # Prefer a set of issues that map to distinct lock groups (max parallelism).
    plan: List[BootstrapPlanItem] = []
    used: Set[str] = set()

    if prefer_unique_locks:
        idx = 0
        for iss in issues:
            if len(plan) >= take:
                break
            it = plan_item(idx, iss)
            if it.lock_group in used:
                continue
            used.add(it.lock_group)
            plan.append(it)
            idx += 1

    # Fill remaining slots (even if lock groups collide)
    idx = len(plan)
    for iss in issues:
        if len(plan) >= take:
            break
        it = plan_item(idx, iss)
        if any(p.issue_number == it.issue_number for p in plan):
            continue
        plan.append(it)
        idx += 1

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
    workflow_override: Optional[str] = None,
) -> None:
    # Preflight
    require_gh = bool(cfg.repo) and (claim or create_prs or run_daemon)
    require_codex = (cfg.default_provider == "codex_cli") and fast
    status = check_tools(require_gh=require_gh, require_docker=False, require_codex=require_codex)
    print_preflight(status)

    st_file, _ = state_paths(root, cfg)

    plan = build_plan_from_queue(
        root,
        cfg,
        agents=agents,
        take=take,
        label=cfg.queue_label,
        workflow_override=workflow_override,
        prefer_unique_locks=True,
    )
    if not plan:
        print(f"No issues found with label '{cfg.queue_label}'. Nothing to do.")
        return

    print("Bootstrap plan:")
    for it in plan:
        labs = ", ".join(it.issue_labels) if it.issue_labels else "-"
        print(f"- {it.agent}: {it.task}  (#{it.issue_number} {it.issue_title})  lock={it.lock_group}  workflow={it.workflow}  labels=[{labs}]")

    # Execute plan
    existing = {(ws.agent, ws.task) for ws in list_workspaces(st_file)}

    for it in plan:
        # If workspace already exists, skip spawn
        if (it.agent, it.task) not in existing:
            ws = spawn_workspace(root, cfg, pol, st_file, agent=it.agent, task=it.task, base_ref=cfg.default_base_ref)
            existing.add((it.agent, it.task))
        else:
            ws = [w for w in list_workspaces(st_file) if w.agent == it.agent and w.task == it.task][0]

        if claim:
            msg = f"Claimed by AgentForge agent '{it.agent}' on host at {time.strftime('%Y-%m-%d %H:%M:%S')}."
            claim_issue(number=it.issue_number, from_label=cfg.queue_label, to_label=cfg.in_progress_label, comment=msg)

        if fast:
            body = view_issue_body(it.issue_number)
            extra_ctx = {
                "issue_number": it.issue_number,
                "issue_title": it.issue_title,
                "issue_url": it.issue_url,
                "issue_labels": ", ".join(it.issue_labels),
                "issue_body": body,
                "lock_group": it.lock_group,
                "create_prs": bool(create_prs),
                "draft_prs": bool(draft_prs),
            }
            summary = run_workflow(
                root=root,
                cfg=cfg,
                pol=pol,
                agent=ws.agent,
                task=ws.task,
                workflow=it.workflow,
                provider_default=cfg.default_provider,
                extra_ctx=extra_ctx,
                dry_run=False,
                log_json=True,
            )
            ok = all(r.ok for r in summary.results)
            if not ok:
                print(f"[FAIL] {it.agent}:{it.task} workflow={it.workflow} (lock={it.lock_group})")
                for r in summary.results:
                    if not r.ok:
                        print(f"  step {r.step_index} ({r.step_type}): {r.message}")
            else:
                if summary.pr_url:
                    print(f"Created PR: {summary.pr_url}")

    if run_daemon:
        from .daemon import run_daemon_forever

        run_daemon_forever(root, cfg, pol, st_file)
