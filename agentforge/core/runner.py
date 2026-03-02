from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, List

from .config import RepoConfig, Policy
from .workspace import Workspace
from .harness import run_harness_step
from .diffscan import scan_diff, git_diff_text, changed_files, numstat_total_changed
from .guardrails import evaluate_policy_globs
from .utils import out, run
from agentforge.providers import get_provider

def _load_env(ws_path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    p = ws_path / ".agentforge.env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env

def _git_has_changes(ws_path: Path) -> bool:
    return bool(out(["git", "status", "--porcelain"], cwd=ws_path).strip())

def _git_commit_all(ws_path: Path, message: str) -> None:
    run(["git", "add", "-A"], cwd=ws_path)
    run(["git", "commit", "-m", message], cwd=ws_path)

def _git_push(ws_path: Path, branch: str, remote: str="origin") -> None:
    run(["git", "push", "-u", remote, branch], cwd=ws_path)

def run_agent_role(root: Path, cfg: RepoConfig, pol: Policy, ws: Workspace, *, provider: str, role: str, prompt: str, auto_commit: bool, auto_push: bool) -> None:
    ws_path = Path(ws.path)
    prov = get_provider(provider)

    env = os.environ.copy()
    env.update(_load_env(ws_path))

    # Role-specific prompt framing (minimal; extend in your project)
    if role == "review":
        diff = git_diff_text(ws_path, base_ref=cfg.default_base_ref)
        prompt = (
            "You are a strict code reviewer. You do NOT execute network calls.\n"
            "Review the following diff and provide actionable feedback.\n\n"
            f"DIFF:\n{diff}\n\n"
            f"EXTRA INSTRUCTIONS:\n{prompt}\n"
        )
    elif role == "qa":
        prompt = (
            "You are a QA agent. Your job is to run the project's harness checks and report failures.\n"
            "Do not make code changes unless necessary to fix test infrastructure.\n\n"
            f"INSTRUCTIONS:\n{prompt}\n"
        )
    elif role == "fix":
        prompt = (
            "You are a fixer agent. Apply the requested changes. Keep edits minimal and consistent.\n"
            "After changes, run harness checks and ensure green.\n\n"
            f"REQUESTED CHANGES:\n{prompt}\n"
        )
    else:  # implement
        prompt = (
            "You are an implementer agent. Implement the task.\n"
            "Follow project conventions, update tests as needed, and keep the diff focused.\n"
            "After changes, run harness checks and ensure green.\n\n"
            f"TASK:\n{prompt}\n"
        )

    res = prov.run(prompt=prompt, cwd=ws_path, env=env)
    if not res.ok:
        raise SystemExit(f"Provider {provider} failed: {res.stderr}")

    # Guardrails: policy glob enforcement
    files = changed_files(ws_path, base_ref=cfg.default_base_ref)
    glob_findings = evaluate_policy_globs(
        changed_files=files,
        forbid_globs=pol.forbid_globs or [],
        protect_globs=pol.protect_globs or [],
        protect_behavior=pol.protect_behavior or "warn",
    )
    blocks = [f for f in glob_findings if f.severity == "block"]
    warns = [f for f in glob_findings if f.severity == "warn"]
    if warns:
        print("Guardrail warnings:")
        for w in warns:
            print(f"- {w.message}")
    if blocks:
        msg = "\n".join(f"- {b.message}" for b in blocks)
        raise SystemExit("Guardrail blocks:\n" + msg)

    # Guardrails: diff scan patterns
    findings = scan_diff(ws_path, base_ref=cfg.default_base_ref)
    high = [f for f in findings if f.severity == "high"]
    if high:
        msg = "\n".join(f"- {f.message}" for f in high)
        raise SystemExit(
            "High-risk changes detected (automation halted).\n" + msg + "\n"
            "Resolve manually or tune policy/scan rules."
        )

    # Guardrails: max changed lines
    total_changed = numstat_total_changed(ws_path, base_ref=cfg.default_base_ref)
    if total_changed > pol.max_changed_lines:
        raise SystemExit(f"Diff too large ({total_changed} changed lines) > policy max_changed_lines={pol.max_changed_lines}")

    # Harness check gate
    if pol.require_harness_check and (cfg.harness_check or []) and role in ["implement", "fix"]:
        run_harness_step(root, cfg, ws, step="check", extra_env=None)

    # Auto commit/push
    if auto_commit and pol.allow_auto_commit and role in ["implement", "fix"]:
        if _git_has_changes(ws_path):
            _git_commit_all(ws_path, message=f"[{ws.agent}] {role}: {ws.task}")
    if auto_push and pol.allow_auto_push and role in ["implement", "fix"]:
        _git_push(ws_path, ws.branch, remote=cfg.default_remote)
