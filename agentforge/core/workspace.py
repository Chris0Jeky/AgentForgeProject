from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import ensure_dir, run, out
from .state import load_state, save_state, state_lock
from .config import RepoConfig, Policy
from .guardrails import sanitize_id

@dataclass(frozen=True)
class Workspace:
    agent: str
    task: str
    path: str
    branch: str
    port: int
    compose_project: Optional[str] = None

def _ws_key(agent: str, task: str) -> str:
    return f"{agent}:{task}"

def _branch_name(agent: str, task: str) -> str:
    return f"af/{sanitize_id(agent)}/{sanitize_id(task)}"

def _folder_name(agent: str, task: str) -> str:
    return f"{sanitize_id(agent)}-{sanitize_id(task)}"

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

def _has_remote(root: Path, remote: str) -> bool:
    try:
        remotes = out(["git", "remote"], cwd=root).splitlines()
        return remote in [r.strip() for r in remotes if r.strip()]
    except Exception:
        return False

def _repair_worktree_metadata(root: Path, wpath: Path) -> None:
    """Best-effort metadata repair for mixed Git toolchains on Windows.

    Some setups mix Git for Windows and MSYS/Cygwin Git, which can leave
    worktree admin pointers in an incompatible path format for subsequent runs.
    """
    try:
        run(["git", "worktree", "repair", str(wpath)], cwd=root)
    except Exception:
        # Keep spawn resilient; a repair failure should not block normal usage.
        pass

def spawn_workspace(root: Path, cfg: RepoConfig, pol: Policy, state_file: Path, *, agent: str, task: str, base_ref: Optional[str]=None) -> Workspace:
    ensure_dir(root / cfg.worktrees_dir)
    wpath = root / cfg.worktrees_dir / _folder_name(agent, task)
    if wpath.exists():
        raise SystemExit(f"Workspace path exists: {wpath}")

    # Fetch remotes (best-effort)
    if _has_remote(root, cfg.default_remote):
        try:
            run(["git", "fetch", cfg.default_remote, "--prune"], cwd=root)
        except Exception:
            pass

    br = _branch_name(agent, task)
    base = base_ref or cfg.default_base_ref
    # If base ref doesn't exist locally (e.g., no remote), fall back to HEAD
    try:
        run(["git", "rev-parse", "--verify", base], cwd=root)
    except Exception:
        base = "HEAD"
    run(["git", "worktree", "add", "-b", br, str(wpath), base], cwd=root)
    _repair_worktree_metadata(root, wpath)

    with state_lock(state_file):
        st = load_state(state_file)
        port = _alloc_port(cfg, st, agent, task, wpath)
        compose_project = f"{cfg.compose_project_prefix}-{sanitize_id(agent)}-{sanitize_id(task)}" if cfg.compose_file else None
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
