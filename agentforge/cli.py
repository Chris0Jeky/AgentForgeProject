#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
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
    run_agent_role(root, cfg, pol, ws, provider=args.provider, role=args.role, prompt=prompt, auto_commit=args.auto_commit, auto_push=args.auto_push)
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
    p_run.add_argument("--provider", default="codex_cli", help="Provider adapter (codex_cli, shell, mock).")
    p_run.add_argument("--role", default="implement", choices=["implement", "review", "fix", "qa"])
    p_run.add_argument("--prompt", default=None)
    p_run.add_argument("--prompt-file", default=None)
    p_run.add_argument("--auto-commit", action="store_true")
    p_run.add_argument("--auto-push", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_d = sub.add_parser("daemon", help="Poll GitHub PR comments for /agentforge commands.")
    p_d.add_argument("--once", action="store_true")
    p_d.set_defaults(func=cmd_daemon)

    return p

def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    rc = args.func(args)
    raise SystemExit(rc)

if __name__ == "__main__":
    main()
