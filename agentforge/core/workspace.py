from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import ensure_dir, run
from .state import load_state, save_state, state_lock
from .config import RepoConfig, Policy

@dataclass(frozen=True)
class Workspace:
    agent: str
    task: str
    path: str
    branch: str
    port: int
    compose_project: Optional[str] = None

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

def _sanitize(s: str) -> str:
    s = s.strip().replace(" ", "-")
    s = _SAFE_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-") or "task"

def _ws_key(agent: str, task: str) -> str:
    return f"{agent}:{task}"

def _branch_name(agent: str, task: str) -> str:
    # Stable and parseable: af/<agent>/<task>
    safe_agent = _sanitize(agent)
    safe_task = _sanitize(task)
    return f"af/{safe_agent}/{safe_task}"

def _folder_name(agent: str, task: str) -> str:
    return f"{_sanitize(agent)}-{_sanitize(task)}"

def _alloc_port(cfg: RepoConfig, st: Dict[str, Any], agent: str, task: str, path: Path) -> int:
    used = {int(p) for p in st.get("ports", {}).keys()}
    for p in range(cfg.port_start, cfg.port_end + 1):
        if p not in used:
            st.setdefault("ports", {})[str(p)] = {
                "agent": agent,
                "task": task,
                "path": str(path),
                "ts": int(time.time()),
            }
            return p
    raise SystemExit("No free ports left in pool")

def spawn_workspace(root: Path, cfg: RepoConfig, pol: Policy, state_file: Path, *, agent: str, task: str, base_ref: Optional[str]=None) -> Workspace:
    ensure_dir(root / cfg.worktrees_dir)
    wpath = root / cfg.worktrees_dir / _folder_name(agent, task)
    if wpath.exists():
        raise SystemExit(f"Workspace path exists: {wpath}")

    # Fetch remotes
    run(["git", "fetch", "origin", "--prune"], cwd=root)

    br = _branch_name(agent, task)
    base = base_ref or cfg.default_base_ref
    run(["git", "worktree", "add", "-b", br, str(wpath), base], cwd=root)

    with state_lock(state_file):
        st = load_state(state_file)
        port = _alloc_port(cfg, st, agent, task, wpath)
        compose_project = f"{cfg.compose_project_prefix}-{_sanitize(agent)}-{_sanitize(task)}" if cfg.compose_file else None
        st.setdefault("workspaces", {})[_ws_key(agent, task)] = {
            "agent": agent,
            "task": task,
            "path": str(wpath),
            "branch": br,
            "port": port,
            "compose_project": compose_project,
            "created_ts": int(time.time()),
        }
        save_state(state_file, st)

    # Write per-workspace env (project-specific env vars are your choice)
    env_path = wpath / ".agentforge.env"
    cache_base = root / cfg.cache_dir / _folder_name(agent, task)
    ensure_dir(cache_base)
    # Generic caches (can be extended per project)
    env = [
        f"AGENTFORGE_AGENT={agent}",
        f"AGENTFORGE_TASK={task}",
        f"AGENTFORGE_PORT={port}",
        f"AGENTFORGE_CACHE={cache_base}",
        f"NUGET_PACKAGES={cache_base / 'nuget'}",
        f"DOTNET_CLI_HOME={cache_base / 'dotnet_home'}",
        f"NPM_CONFIG_CACHE={cache_base / 'npm_cache'}",
    ]
    ensure_dir(cache_base / "nuget")
    ensure_dir(cache_base / "dotnet_home")
    ensure_dir(cache_base / "npm_cache")
    env_path.write_text("\n".join(env) + "\n", encoding="utf-8")

    # direnv convenience
    (wpath / ".envrc").write_text("dotenv_if_exists .agentforge.env\n", encoding="utf-8")
    # PowerShell env loader convenience
    (wpath / "set-env.ps1").write_text(
        """Get-Content .agentforge.env | ForEach-Object {
  if ($_ -match '^(\\w+)=(.*)$') {
    [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2])
  }
}
Write-Host "Loaded .agentforge.env into this process environment."
""",
        encoding="utf-8"
    )

    return Workspace(agent=agent, task=task, path=str(wpath), branch=br, port=port, compose_project=compose_project)

def list_workspaces(state_file: Path) -> List[Workspace]:
    st = load_state(state_file)
    items = st.get("workspaces", {})
    out_ws: List[Workspace] = []
    for _, v in items.items():
        out_ws.append(
            Workspace(
                agent=v["agent"],
                task=v["task"],
                path=v["path"],
                branch=v["branch"],
                port=int(v["port"]),
                compose_project=v.get("compose_project"),
            )
        )
    # Stable ordering
    out_ws.sort(key=lambda w: (w.agent, w.task))
    return out_ws

def remove_workspace(root: Path, cfg: RepoConfig, state_file: Path, *, agent: str, task: str, delete_branch: bool=False) -> None:
    k = _ws_key(agent, task)
    with state_lock(state_file):
        st = load_state(state_file)
        ws = st.get("workspaces", {}).get(k)
        if not ws:
            raise SystemExit(f"Workspace not found in state: {k}")
        port = int(ws["port"])
        st.get("ports", {}).pop(str(port), None)
        st.get("workspaces", {}).pop(k, None)
        save_state(state_file, st)

    wpath = Path(ws["path"])
    run(["git", "worktree", "remove", "--force", str(wpath)], cwd=root)

    if delete_branch:
        try:
            run(["git", "branch", "-D", ws["branch"]], cwd=root)
        except Exception:
            pass
