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
from .mcp import load_mcp_config, ensure_gateway_running
from .guardrails import matches_any_glob

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

def _status_changed_paths_from_porcelain(porcelain: str) -> List[str]:
    paths: List[str] = []
    for line in (porcelain or "").splitlines():
        if not line:
            continue
        # Porcelain v1: XY <path>  or  R  old -> new
        path_part = line[3:] if len(line) >= 4 else line
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        p = path_part.strip()
        if p.startswith('"') and p.endswith('"') and len(p) >= 2:
            p = p[1:-1]
        if p:
            paths.append(p.replace("\\", "/"))
    # Stable + unique while preserving order
    seen = set()
    out_paths: List[str] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        out_paths.append(p)
    return out_paths

def _working_tree_changed_files(ws_path: Path) -> List[str]:
    txt = out(["git", "status", "--porcelain"], cwd=ws_path)
    return _status_changed_paths_from_porcelain(txt)

def _violating_paths(changed_paths: List[str], allowed_globs: List[str]) -> List[str]:
    if not allowed_globs:
        return []
    bad: List[str] = []
    for p in changed_paths:
        if not matches_any_glob(p, allowed_globs):
            bad.append(p)
    return bad

def run_agent_role(
    root: Path,
    cfg: RepoConfig,
    pol: Policy,
    ws: Workspace,
    *,
    provider: str,
    role: str,
    prompt: str,
    auto_commit: bool,
    auto_push: bool,
    surgical: bool = False,
    allowed_edit_globs: Optional[List[str]] = None,
) -> None:
    ws_path = Path(ws.path)
    prov = get_provider(provider)
    allowed_globs = [g.strip() for g in (allowed_edit_globs or []) if str(g).strip()]
    if surgical and not allowed_globs:
        raise SystemExit("Surgical mode requires at least one allowed edit glob.")

    env = os.environ.copy()
    env.update(_load_env(ws_path))

    # Optional: MCP Gateway sidecar (Docker MCP Toolkit).
    mcp_hint = ""
    try:
        mcfg = load_mcp_config(root)
        if mcfg.gateway_auto_start:
            gw_key = f"{ws.agent}::{ws.task}" if mcfg.gateway_per_workspace else None
            gw = ensure_gateway_running(root, cfg, mcfg, key=gw_key)
            if gw.get("url"):
                env["AGENTFORGE_MCP_GATEWAY_URL"] = str(gw["url"])
                env.setdefault("MCP_GATEWAY_URL", str(gw["url"]))
            if gw.get("auth_token"):
                env["AGENTFORGE_MCP_GATEWAY_AUTH_TOKEN"] = str(gw["auth_token"])
                # Some clients may look for this name.
                env.setdefault("MCP_GATEWAY_AUTH_TOKEN", str(gw["auth_token"]))
            env["AGENTFORGE_MCP_PROFILE"] = str(gw.get("profile") or mcfg.profile)
            env["AGENTFORGE_MCP_TRANSPORT"] = str(gw.get("transport") or mcfg.gateway_transport)
            if mcfg.gateway_inject_prompt:
                mcp_hint = (
                    "\n\n[MCP]\n"
                    "A Docker MCP Gateway is available for tool calls.\n"
                    f"URL: {gw.get('url','')}\n"
                    f"AUTH_TOKEN: {gw.get('auth_token','')}\n"
                    f"PROFILE: {gw.get('profile') or mcfg.profile}\n"
                    f"TRANSPORT: {gw.get('transport') or mcfg.gateway_transport}\n"
                )
    except Exception:
        # MCP is optional; ignore errors by default.
        mcp_hint = ""

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
            "Execution policy:\n"
            "- The TASK text below is authoritative.\n"
            "- If TASK limits scope to explicit file(s), modify only those files and skip broad repository scans.\n"
            "- Do not run install/test/lint harness commands unless TASK explicitly requests it.\n"
            "AgentForge will run harness checks after your edits.\n\n"
            f"TASK:\n{prompt}\n"
        )
    else:  # implement
        prompt = (
            "You are an implementer agent. Implement the task.\n"
            "Follow project conventions and keep the diff focused.\n"
            "Execution policy:\n"
            "- The TASK text below is authoritative.\n"
            "- If TASK limits scope to explicit file(s), modify only those files and skip broad repository scans.\n"
            "- Do not run install/test/lint harness commands unless TASK explicitly requests it.\n"
            "AgentForge will run harness checks after your edits.\n\n"
            f"TASK:\n{prompt}\n"
        )

    if surgical:
        allow_txt = "\n".join(f"- {g}" for g in allowed_globs)
        prompt += (
            "\n\n[SURGICAL MODE]\n"
            "Strict constraint: only modify files matching one of these glob patterns:\n"
            f"{allow_txt}\n"
            "If you need to touch any other file, stop and explain why instead of editing.\n"
        )

    if mcp_hint:
        prompt += mcp_hint

    res = prov.run(prompt=prompt, cwd=ws_path, env=env)
    if not res.ok:
        raise SystemExit(f"Provider {provider} failed: {res.stderr}")

    if surgical:
        changed_now = _working_tree_changed_files(ws_path)
        bad = _violating_paths(changed_now, allowed_globs)
        if bad:
            details = "\n".join(f"- {p}" for p in bad)
            raise SystemExit(
                "Surgical mode violation: changed files outside allowlist.\n"
                f"Allowed globs: {', '.join(allowed_globs)}\n"
                f"Out-of-scope files:\n{details}"
            )

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
