from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

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
    agents: Optional[List[str]] = None,
    take: int = 3,
    label: Optional[str] = None,
    workflow_override: Optional[str] = None,
    prefer_unique_locks: bool = True,
) -> List[BootstrapPlanItem]:
    """Build a deterministic "bootstrap plan" from GitHub issues in a queue label.

    - If lock groups are configured (.agentforge/locks.toml), we attempt to route
      issues to a lock group based on labels/title keywords.
    - If prefer_unique_locks is True, we try to select items with distinct lock
      groups first, to reduce contention.
    """
    label = label or cfg.queue_label
    issues = list_issues(label=label, limit=50)

    if not issues:
        return []

    agents = agents or _default_agents(take)
    if not agents:
        agents = _default_agents(take)

    groups = load_lock_groups(root)

    def plan_item(idx: int, iss) -> BootstrapPlanItem:
        agent_name = agents[idx % len(agents)]
        task_name = f"issue-{iss.number}"

        spec = select_lock_group_for_issue(
            groups,
            issue_labels=list(iss.labels or []),
            issue_title=str(iss.title or ""),
            strategy=cfg.auto_lock_strategy,
        )
        lock_group = spec.name if spec else "repo"
        wf = workflow_override or (spec.workflow if spec and spec.workflow else cfg.default_workflow)
        return BootstrapPlanItem(
            agent=agent_name,
            task=task_name,
            issue_number=iss.number,
            issue_title=iss.title,
            issue_url=iss.url,
            issue_labels=list(iss.labels or []),
            lock_group=lock_group,
            workflow=wf,
        )

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
    event_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Bootstrap N agents from a GitHub issue queue.

    If event_cb is provided, the function emits structured events instead of printing
    verbose output (CLI output is still printed when event_cb is None).
    """
    def emit(ev: Dict[str, Any]) -> None:
        if not event_cb:
            return
        try:
            event_cb(ev)
        except Exception:
            return

    def log(msg: str) -> None:
        # CLI-friendly output when not running under UI/background jobs.
        if not event_cb:
            print(msg)

    emit({"type": "bootstrap_start", "agents": agents, "take": take, "fast": fast, "claim": claim, "create_prs": create_prs, "draft_prs": draft_prs})

    # Preflight
    require_gh = bool(cfg.repo) and (claim or create_prs or run_daemon)
    require_codex = (cfg.default_provider == "codex_cli") and fast
    status = check_tools(require_gh=require_gh, require_docker=False, require_codex=require_codex)
    if not event_cb:
        print_preflight(status)
    else:
        status_items: List[Dict[str, Any]] = []
        for s in status:
            if isinstance(s, dict):
                status_items.append(dict(s))
            elif hasattr(s, "__dict__"):
                status_items.append(dict(getattr(s, "__dict__")))
            else:
                status_items.append({"value": str(s)})
        emit({"type": "preflight", "status": status_items})

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
        msg = f"No issues found with label '{cfg.queue_label}'. Nothing to do."
        log(msg)
        emit({"type": "bootstrap_end", "ok": True, "message": msg})
        return

    if not event_cb:
        log("Bootstrap plan:")
        for it in plan:
            labs = ", ".join(it.issue_labels) if it.issue_labels else "-"
            log(f"- {it.agent}: {it.task}  (#{it.issue_number} {it.issue_title})  lock={it.lock_group}  workflow={it.workflow}  labels=[{labs}]")
    emit(
        {
            "type": "bootstrap_plan",
            "items": [
                {
                    "agent": it.agent,
                    "task": it.task,
                    "issue_number": it.issue_number,
                    "issue_title": it.issue_title,
                    "issue_url": it.issue_url,
                    "labels": it.issue_labels,
                    "lock_group": it.lock_group,
                    "workflow": it.workflow,
                }
                for it in plan
            ],
        }
    )

    # Execute plan
    existing = {(ws.agent, ws.task) for ws in list_workspaces(st_file)}
    ok_all = True

    for it in plan:
        emit({"type": "bootstrap_item_start", "agent": it.agent, "task": it.task, "issue_number": it.issue_number, "lock_group": it.lock_group, "workflow": it.workflow})

        # If workspace already exists, skip spawn
        if (it.agent, it.task) not in existing:
            ws = spawn_workspace(root, cfg, pol, st_file, agent=it.agent, task=it.task, base_ref=cfg.default_base_ref)
            existing.add((it.agent, it.task))
            emit({"type": "workspace_spawned", "agent": it.agent, "task": it.task, "path": ws.path, "branch": ws.branch})
        else:
            ws = [w for w in list_workspaces(st_file) if w.agent == it.agent and w.task == it.task][0]
            emit({"type": "workspace_exists", "agent": it.agent, "task": it.task, "path": ws.path, "branch": ws.branch})

        if claim:
            msg = f"Claimed by AgentForge agent '{it.agent}' on host at {time.strftime('%Y-%m-%d %H:%M:%S')}."
            claim_issue(number=it.issue_number, from_label=cfg.queue_label, to_label=cfg.in_progress_label, comment=msg)
            emit({"type": "issue_claimed", "issue_number": it.issue_number, "from_label": cfg.queue_label, "to_label": cfg.in_progress_label})

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

            def wf_emit(ev: Dict[str, Any]) -> None:
                # annotate workflow events with bootstrap context
                ev2 = dict(ev or {})
                ev2.setdefault("bootstrap", {})
                ev2["bootstrap"].update({"issue_number": it.issue_number, "agent": ws.agent, "task": ws.task, "lock_group": it.lock_group, "workflow": it.workflow})
                emit(ev2)

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
                event_cb=wf_emit if event_cb else None,
            )
            ok = all(r.ok for r in summary.results)
            if not ok:
                ok_all = False
                log(f"[FAIL] {it.agent}:{it.task} workflow={it.workflow} (lock={it.lock_group})")
                for r in summary.results:
                    if not r.ok:
                        log(f"  step {r.step_index} ({r.step_type}): {r.message}")
            else:
                if summary.pr_url:
                    log(f"Created PR: {summary.pr_url}")
            emit({"type": "bootstrap_item_end", "agent": it.agent, "task": it.task, "issue_number": it.issue_number, "ok": ok, "pr_url": summary.pr_url})
        else:
            emit({"type": "bootstrap_item_end", "agent": it.agent, "task": it.task, "issue_number": it.issue_number, "ok": True, "pr_url": None})

    emit({"type": "bootstrap_end", "ok": ok_all})

    if run_daemon:
        from .daemon import run_daemon_forever

        run_daemon_forever(root, cfg, pol, st_file)
