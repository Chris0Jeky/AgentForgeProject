#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    run_agent_role(root, cfg, pol, ws, provider=args.provider or cfg.default_provider, role=args.role, prompt=prompt, auto_commit=args.auto_commit, auto_push=args.auto_push)
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
        print(f"#{iss.number}: {iss.title}  ({iss.url})")
    return 0

def cmd_bootstrap(args: argparse.Namespace) -> int:
    root = find_repo_root(Path(args.repo) if args.repo else None)
    # Ensure init exists (convenience)
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
    serve_status(root, cfg, pol, st_file, host=args.host, port=args.port)
    return 0

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
    p_boot.set_defaults(func=cmd_bootstrap)

    p_d = sub.add_parser("daemon", help="Poll GitHub PR comments for /agentforge commands.")
    p_d.add_argument("--once", action="store_true")
    p_d.set_defaults(func=cmd_daemon)

    p_wh = sub.add_parser("webhook", help="Handle a single GitHub event payload (e.g. issue_comment JSON).")
    p_wh.add_argument("--event-file", required=True, help="Path to GitHub event JSON (e.g. $GITHUB_EVENT_PATH).")
    p_wh.set_defaults(func=cmd_webhook)

    p_sv = sub.add_parser("serve", help="Serve a local read-only dashboard.")
    p_sv.add_argument("--host", default="127.0.0.1")
    p_sv.add_argument("--port", type=int, default=5179)
    p_sv.set_defaults(func=cmd_serve)

    return p

def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    rc = args.func(args)
    raise SystemExit(rc)

if __name__ == "__main__":
    main()
