#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agentforge.core.config import find_repo_root, load_repo_config
from agentforge.core.state import state_paths
from agentforge.core.workspace import (
    spawn_workspace,
    list_workspaces,
    remove_workspace,
)
from agentforge.core.harness import run_harness_step
from agentforge.core.daemon import run_daemon_once, run_daemon_forever
from agentforge.core.policy import policy_summary
from agentforge.core.runner import run_agent_role

def cmd_init(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    from agentforge.core.init import init_repo
    init_repo(root, overwrite=args.overwrite)
    print(f"Initialized AgentForge in: {root}")
    return 0

def cmd_spawn(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    ws = spawn_workspace(root, cfg, pol, st_file, agent=args.agent, task=args.task, base_ref=args.base_ref)
    print(f"Spawned workspace: {ws.path}")
    print(f"  branch: {ws.branch}")
    print(f"  port:   {ws.port}")
    return 0

def cmd_list(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    wss = list_workspaces(st_file)
    if not wss:
        print("No workspaces tracked.")
        return 0
    for ws in wss:
        print(f"- {ws.agent}:{ws.task}  path={ws.path}  branch={ws.branch}  port={ws.port}")
    return 0

def cmd_rm(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    remove_workspace(root, cfg, st_file, agent=args.agent, task=args.task, delete_branch=args.delete_branch)
    print(f"Removed workspace {args.agent}:{args.task}")
    return 0

def cmd_status(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    wss = list_workspaces(st_file)
    print("AgentForge status")
    print(policy_summary(pol))
    print("")
    if not wss:
        print("No workspaces tracked.")
        return 0
    for ws in wss:
        print(f"- {ws.agent}:{ws.task}")
        print(f"    path:   {ws.path}")
        print(f"    branch: {ws.branch}")
        print(f"    port:   {ws.port}")
        if ws.compose_project:
            print(f"    compose: {ws.compose_project}")
    return 0

def cmd_harness(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    wss = { (ws.agent, ws.task): ws for ws in list_workspaces(st_file) }
    ws = wss.get((args.agent, args.task))
    if not ws:
        raise SystemExit("Workspace not found. Use agentforge list.")
    ok = run_harness_step(root, cfg, ws, step=args.step, extra_env=None)
    return 0 if ok else 2

def cmd_run(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    wss = { (ws.agent, ws.task): ws for ws in list_workspaces(st_file) }
    ws = wss.get((args.agent, args.task))
    if not ws:
        raise SystemExit("Workspace not found. Use agentforge spawn.")
    prompt = args.prompt
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    if not prompt:
        raise SystemExit("Provide --prompt or --prompt-file")
    allow_globs = [g for g in (args.allow_edit_glob or []) if str(g).strip()]
    surgical = bool(args.surgical or allow_globs)
    run_agent_role(
        root,
        cfg,
        pol,
        ws,
        provider=args.provider or cfg.default_provider,
        role=args.role,
        prompt=prompt,
        auto_commit=args.auto_commit,
        auto_push=args.auto_push,
        surgical=surgical,
        allowed_edit_globs=allow_globs,
    )
    return 0

def cmd_daemon(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    if args.once:
        run_daemon_once(root, cfg, pol, st_file)
    else:
        run_daemon_forever(root, cfg, pol, st_file)
    return 0

def cmd_webhook(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    from agentforge.core.webhook import handle_github_event_file
    handle_github_event_file(root, cfg, pol, st_file, event_path=Path(args.event_file))
    return 0

def cmd_queue_list(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.queue import list_issues
    issues = list_issues(label=args.label or cfg.queue_label, limit=args.limit)
    if not issues:
        print("No issues found.")
        return 0
    for iss in issues:
        labs = ", ".join(getattr(iss, "labels", []) or [])
        lab_s = f" [{labs}]" if labs else ""
        print(f"#{iss.number}: {iss.title}{lab_s}  ({iss.url})")
    return 0

def cmd_bootstrap(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    from agentforge.core.init import init_repo
    if not (root / ".agentforge" / "config.toml").exists():
        init_repo(root, overwrite=False)
        print("Initialized .agentforge/ (config + policy templates). Please edit .agentforge/config.toml then re-run bootstrap.")
        return 0

    cfg, pol = load_repo_config(root)

    from agentforge.core.bootstrap import run_bootstrap
    agents = []
    if args.agents:
        agents = [a.strip() for a in args.agents.split(",") if a.strip()]
    run_bootstrap(
        root,
        cfg,
        pol,
        agents=agents,
        take=args.take,
        fast=args.fast,
        claim=args.claim,
        create_prs=args.create_prs,
        draft_prs=not args.no_draft,
        run_daemon=args.daemon,
        workflow_override=args.workflow,
    )
    return 0

def cmd_pr_create(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    wss = { (ws.agent, ws.task): ws for ws in list_workspaces(st_file) }
    ws = wss.get((args.agent, args.task))
    if not ws:
        raise SystemExit("Workspace not found. Use agentforge spawn.")
    from agentforge.core.pr import create_pr
    title = args.title or f"[{ws.agent}] {ws.task}"
    body = args.body or "Automated by AgentForge."
    pr = create_pr(ws_path=Path(ws.path), title=title, body=body, base=cfg.default_base_branch, head=ws.branch, draft=not args.no_draft)
    print(pr.url)
    return 0

def cmd_serve(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    from agentforge.core.server import serve_status
    serve_status(root, cfg, pol, st_file, host=args.host, port=args.port, enable_actions=args.actions, token=args.token)
    return 0


def cmd_mcp_gateway_list(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.mcp import list_gateways

    gws = list_gateways(root, cfg)
    print(json.dumps({"gateways": gws}, indent=2))
    return 0


def cmd_mcp_gateway_start(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.mcp import load_mcp_config, ensure_gateway_running

    mcfg = load_mcp_config(root)
    key = args.key.strip() if args.key else None
    transport = args.transport.strip() if args.transport else None
    gw = ensure_gateway_running(root, cfg, mcfg, key=key, transport=transport)
    print(json.dumps(gw, indent=2))
    return 0


def cmd_mcp_gateway_stop(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.mcp import stop_gateway

    key = args.key.strip() if args.key else None
    stop_gateway(root, cfg, key=key)
    print("ok")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    st_file, _ = state_paths(root, cfg)
    from agentforge.core.server import serve_status
    serve_status(root, cfg, pol, st_file, host=args.host, port=args.port, enable_actions=True, token=args.token)
    return 0


def cmd_mcp_status(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    # config/policy are not required, but init ensures .agentforge exists
    cfg, pol = load_repo_config(root)
    from agentforge.core.mcp import load_mcp_config, docker_mcp_available, docker_mcp_version
    mcfg = load_mcp_config(root)
    print("MCP config (.agentforge/mcp.toml):")
    print(f"  backend     : {mcfg.backend}")
    print(f"  catalog_ref : {mcfg.catalog_ref}")
    print(f"  profile     : {mcfg.profile}")
    print(f"  servers     : {', '.join(mcfg.servers or []) or '(none)'}")
    print()
    print(f"docker mcp available: {docker_mcp_available()}")
    ver = docker_mcp_version()
    if ver:
        print("docker mcp version:")
        print(ver)
    return 0

def cmd_mcp_catalog(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.mcp import load_mcp_config, docker_mcp_available, docker_catalog_server_ls
    mcfg = load_mcp_config(root)
    if not docker_mcp_available():
        raise SystemExit("docker mcp not available. Install Docker Desktop MCP Toolkit or the docker-mcp plugin.")
    servers = docker_catalog_server_ls(mcfg.catalog_ref)
    if args.filter:
        f = args.filter.strip().lower()
        servers = [s for s in servers if f in s.lower()]
    for s in servers:
        print(s)
    return 0

def cmd_mcp_profile(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.mcp import load_mcp_config, docker_mcp_available, docker_profile_list, docker_profile_server_ls
    mcfg = load_mcp_config(root)
    if not docker_mcp_available():
        raise SystemExit("docker mcp not available.")
    print("Profiles:")
    for p in docker_profile_list():
        mark = " (this repo)" if p == mcfg.profile else ""
        print(f"- {p}{mark}")
    print()
    print(f"Servers in profile '{mcfg.profile}':")
    print(docker_profile_server_ls(mcfg.profile))
    return 0

def cmd_mcp_sync(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.mcp import load_mcp_config, docker_mcp_available, docker_sync_profile
    mcfg = load_mcp_config(root)
    if not docker_mcp_available():
        raise SystemExit("docker mcp not available.")
    docker_sync_profile(mcfg)
    print(f"Synced profile '{mcfg.profile}' with servers: {', '.join(mcfg.servers or []) or '(none)'}")
    return 0

def cmd_mcp_add(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.mcp import load_mcp_config, docker_mcp_available, docker_sync_profile, McpConfig
    mcfg = load_mcp_config(root)
    if not docker_mcp_available():
        raise SystemExit("docker mcp not available.")
    sid = args.server.strip()
    docker_sync_profile(McpConfig(backend=mcfg.backend, catalog_ref=mcfg.catalog_ref, profile=mcfg.profile, servers=[sid]))
    print(f"Added '{sid}' to profile '{mcfg.profile}'")
    return 0


def cmd_lock_list(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.locks import list_locks, is_expired
    locks = list_locks(root=root, cfg=cfg)
    if not locks:
        print("No locks held.")
        return 0
    for l in locks:
        exp = "expired" if is_expired(l) else "active"
        print(f"- {l.group}: {l.agent}:{l.task} host={l.hostname} pid={l.pid} ({exp})")
    return 0

def cmd_lock_acquire(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.locks import acquire_lock
    info = acquire_lock(root=root, cfg=cfg, group=args.group, agent=args.agent, task=args.task, ttl_sec=args.ttl, force=args.force)
    print(f"Acquired {info.group} for {info.agent}:{info.task}")
    return 0

def cmd_lock_release(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.locks import release_lock
    release_lock(root=root, cfg=cfg, group=args.group, agent=args.agent, task=args.task, force=args.force)
    print(f"Released {args.group}")
    return 0


def cmd_lock_maintain(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.lock_maintenance import maintain_sticky_locks

    interval = int(args.interval or 0) or int(getattr(cfg, "lock_renew_interval_sec", 120) or 120)
    dry_run = bool(args.dry_run)

    def once() -> None:
        actions = maintain_sticky_locks(root, cfg, dry_run=dry_run)
        if not actions:
            print("(no sticky locks)")
            return
        for a in actions:
            pr = f" PR#{a.pr_number}" if a.pr_number else ""
            print(f"{a.action:8s} {a.group}{pr}  {a.reason}")

    if args.forever:
        print(f"Maintaining sticky locks every {interval}s (dry_run={dry_run})")
        while True:
            once()
            time.sleep(interval)
    else:
        once()
    return 0


def cmd_workflow_run(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    cfg, pol = load_repo_config(root)
    from agentforge.core.workflow import run_workflow
    summary = run_workflow(
        root=root, cfg=cfg, pol=pol,
        agent=args.agent, task=args.task, workflow=args.workflow,
        provider_default=args.provider, extra_ctx=None,
        dry_run=args.dry_run,
        log_json=not args.no_log,
    )
    ok = all(r.ok for r in summary.results)
    for r in summary.results:
        mark = "OK" if r.ok else "FAIL"
        msg = f" - {r.message}" if r.message else ""
        print(f"[{mark}] step {r.step_index} ({r.step_type}){msg}")
    if summary.pr_url:
        print(f"PR: {summary.pr_url}")
    return 0 if ok else 2

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentforge", description="Local-first agent farm built on git worktrees.")
    p.add_argument("--repo", default=None, help="Path to git repo (defaults to current repo).")

    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize AgentForge files in this repo (.agentforge/*).")
    p_init.add_argument("--overwrite", action="store_true", help="Overwrite existing AgentForge templates.")
    p_init.set_defaults(func=cmd_init)

    p_spawn = sub.add_parser("spawn", help="Create an isolated worktree workspace for an agent+task.")
    p_spawn.add_argument("--agent", required=True)
    p_spawn.add_argument("--task", required=True)
    p_spawn.add_argument("--base-ref", default=None, help="Base ref (default from config).")
    p_spawn.set_defaults(func=cmd_spawn)

    p_ls = sub.add_parser("list", help="List tracked workspaces.")
    p_ls.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("rm", help="Remove a workspace (optionally deletes its branch).")
    p_rm.add_argument("--agent", required=True)
    p_rm.add_argument("--task", required=True)
    p_rm.add_argument("--delete-branch", action="store_true")
    p_rm.set_defaults(func=cmd_rm)

    p_status = sub.add_parser("status", help="Show policy + tracked workspace status.")
    p_status.set_defaults(func=cmd_status)

    p_h = sub.add_parser("harness", help="Run a harness step (setup/check) in a workspace.")
    p_h.add_argument("--agent", required=True)
    p_h.add_argument("--task", required=True)
    p_h.add_argument("--step", required=True, choices=["setup", "check"])
    p_h.set_defaults(func=cmd_harness)

    p_run = sub.add_parser("run", help="Run an agent role (implement/review/fix/qa) in a workspace.")
    p_run.add_argument("--agent", required=True)
    p_run.add_argument("--task", required=True)
    p_run.add_argument("--provider", default=None, help="Provider adapter (codex_cli, shell, mock, or plugin).")
    p_run.add_argument("--role", default="implement", choices=["implement", "review", "fix", "qa"])
    p_run.add_argument("--prompt", default=None)
    p_run.add_argument("--prompt-file", default=None)
    p_run.add_argument("--surgical", action="store_true", help="Enforce edit scope with --allow-edit-glob.")
    p_run.add_argument("--allow-edit-glob", action="append", default=[], help="Allowed file glob for surgical mode (repeatable).")
    p_run.add_argument("--auto-commit", action="store_true")
    p_run.add_argument("--auto-push", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_pr = sub.add_parser("pr", help="PR utilities.")
    pr_sub = p_pr.add_subparsers(dest="pr_cmd", required=True)
    p_prc = pr_sub.add_parser("create", help="Create a PR for a workspace branch using gh.")
    p_prc.add_argument("--agent", required=True)
    p_prc.add_argument("--task", required=True)
    p_prc.add_argument("--title", default=None)
    p_prc.add_argument("--body", default=None)
    p_prc.add_argument("--no-draft", action="store_true")
    p_prc.set_defaults(func=cmd_pr_create)

    p_q = sub.add_parser("queue", help="Issue queue utilities (GitHub).")
    q_sub = p_q.add_subparsers(dest="q_cmd", required=True)
    p_ql = q_sub.add_parser("list", help="List queued issues (by label).")
    p_ql.add_argument("--label", default=None)
    p_ql.add_argument("--limit", type=int, default=20)
    p_ql.set_defaults(func=cmd_queue_list)

    p_boot = sub.add_parser("bootstrap", help="One-command flow: pull from queue, spawn, optionally run agent, create PR, start daemon.")
    p_boot.add_argument("--agents", default=None, help="Comma-separated agent IDs (e.g. a1,a2,a3).")
    p_boot.add_argument("--take", type=int, default=2, help="How many queued issues to take.")
    p_boot.add_argument("--fast", action="store_true", help="Actually run implementer agents + push.")
    p_boot.add_argument("--claim", action="store_true", help="Move issue label from queue -> in-progress and comment.")
    p_boot.add_argument("--create-prs", action="store_true", help="Create draft PRs after pushing.")
    p_boot.add_argument("--no-draft", action="store_true", help="Create non-draft PRs.")
    p_boot.add_argument("--daemon", action="store_true", help="Run PR comment daemon after bootstrap (blocks).")
    p_boot.add_argument("--workflow", default=None, help="Workflow override (default: auto-selected per lock group).")
    p_boot.set_defaults(func=cmd_bootstrap)

    p_wf = sub.add_parser("workflow", help="Workflow engine (repo-local workflows.toml).")
    wf_sub = p_wf.add_subparsers(dest="wf_cmd", required=True)
    p_wfr = wf_sub.add_parser("run", help="Run a named workflow for an existing workspace.")
    p_wfr.add_argument("--workflow", required=True)
    p_wfr.add_argument("--agent", required=True)
    p_wfr.add_argument("--task", required=True)
    p_wfr.add_argument("--provider", default=None, help="Override provider for agent steps.")
    p_wfr.add_argument("--dry-run", action="store_true")
    p_wfr.add_argument("--no-log", action="store_true", help="Disable writing JSON run summaries to .agentforge/logs.")
    p_wfr.set_defaults(func=cmd_workflow_run)

    p_lock = sub.add_parser("lock", help="Local subsystem locks (exclusive).")
    lock_sub = p_lock.add_subparsers(dest="lock_cmd", required=True)
    p_ll = lock_sub.add_parser("list", help="List held locks.")
    p_ll.set_defaults(func=cmd_lock_list)
    p_la = lock_sub.add_parser("acquire", help="Acquire a lock.")
    p_la.add_argument("--group", required=True)
    p_la.add_argument("--agent", required=True)
    p_la.add_argument("--task", required=True)
    p_la.add_argument("--ttl", type=int, default=6*60*60)
    p_la.add_argument("--force", action="store_true")
    p_la.set_defaults(func=cmd_lock_acquire)
    p_lr = lock_sub.add_parser("release", help="Release a lock.")
    p_lr.add_argument("--group", required=True)
    p_lr.add_argument("--agent", required=True)
    p_lr.add_argument("--task", required=True)
    p_lr.add_argument("--force", action="store_true")
    p_lr.set_defaults(func=cmd_lock_release)

    p_lm = lock_sub.add_parser("maintain", help="Renew sticky locks and optionally auto-release on merged/closed PRs.")
    p_lm.add_argument("--dry-run", action="store_true", help="Do not modify locks; just report actions.")
    p_lm.add_argument("--forever", action="store_true", help="Run maintenance loop forever.")
    p_lm.add_argument("--interval", type=int, default=0, help="Override maintenance interval seconds.")
    p_lm.set_defaults(func=cmd_lock_maintain)

    p_mcp = sub.add_parser("mcp", help="Manage MCP setup (Docker MCP Toolkit).")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_cmd", required=True)

    p_ms = mcp_sub.add_parser("status", help="Show MCP configuration and docker-mcp availability.")
    p_ms.set_defaults(func=cmd_mcp_status)

    p_mc = mcp_sub.add_parser("catalog", help="List catalog server IDs.")
    p_mc.add_argument("--filter", default=None, help="Substring filter.")
    p_mc.set_defaults(func=cmd_mcp_catalog)

    p_mp = mcp_sub.add_parser("profile", help="Show profile servers for this repo.")
    p_mp.set_defaults(func=cmd_mcp_profile)

    p_msync = mcp_sub.add_parser("sync", help="Ensure profile exists and add servers from .agentforge/mcp.toml.")
    p_msync.set_defaults(func=cmd_mcp_sync)

    p_madd = mcp_sub.add_parser("add", help="Add a server (by server-id) to the configured profile.")
    p_madd.add_argument("--server", required=True, help="Server ID from the catalog (e.g. playwright).")
    p_madd.set_defaults(func=cmd_mcp_add)

    p_mgw = mcp_sub.add_parser("gateway", help="Manage Docker MCP Gateway (optional).")
    gw_sub = p_mgw.add_subparsers(dest="mcp_gw_cmd", required=True)

    p_gwl = gw_sub.add_parser("list", help="List known gateways started by AgentForge.")
    p_gwl.set_defaults(func=cmd_mcp_gateway_list)

    p_gws = gw_sub.add_parser("start", help="Start (or ensure) a gateway.")
    p_gws.add_argument("--key", default=None, help="Scope key (default: global). Example: a1::issue-123")
    p_gws.add_argument("--transport", default=None, choices=["sse", "streaming"], help="Override transport.")
    p_gws.set_defaults(func=cmd_mcp_gateway_start)

    p_gwst = gw_sub.add_parser("stop", help="Stop a gateway.")
    p_gwst.add_argument("--key", default=None, help="Scope key (default: global).")
    p_gwst.set_defaults(func=cmd_mcp_gateway_stop)

    p_d = sub.add_parser("daemon", help="Poll GitHub PR comments for /agentforge commands.")
    p_d.add_argument("--once", action="store_true")
    p_d.set_defaults(func=cmd_daemon)

    p_wh = sub.add_parser("webhook", help="Handle a single GitHub event payload (e.g. issue_comment JSON).")
    p_wh.add_argument("--event-file", required=True, help="Path to GitHub event JSON (e.g. $GITHUB_EVENT_PATH).")
    p_wh.set_defaults(func=cmd_webhook)

    p_sv = sub.add_parser("serve", help="Serve the local dashboard UI.")
    p_sv.add_argument("--host", default="127.0.0.1")
    p_sv.add_argument("--port", type=int, default=5179)
    p_sv.add_argument("--actions", action="store_true", help="Enable POST actions (spawning, locks, workflow runs).")
    p_sv.add_argument("--token", default=None, help="Token for POST actions (auto-generated if omitted).")
    p_sv.set_defaults(func=cmd_serve)

    p_ui = sub.add_parser("ui", help="Start the local UI with actions enabled.")
    p_ui.add_argument("--host", default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=5179)
    p_ui.add_argument("--token", default=None, help="Token for POST actions (auto-generated if omitted).")
    p_ui.set_defaults(func=cmd_ui)

    return p

def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    rc = args.func(args)
    raise SystemExit(rc)

if __name__ == "__main__":
    main()
