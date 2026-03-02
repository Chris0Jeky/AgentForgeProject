from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from .config import RepoConfig
from .workspace import Workspace
from .utils import run, shell_cmd

def _load_env_file(ws_path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    p = ws_path / ".agentforge.env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k] = v
    return env

def run_harness_step(root: Path, cfg: RepoConfig, ws: Workspace, *, step: str, extra_env: Optional[Dict[str, str]]=None) -> bool:
    ws_path = Path(ws.path)
    env = os.environ.copy()
    env.update(_load_env_file(ws_path))
    if extra_env:
        env.update(extra_env)

    if step == "setup":
        cmds = cfg.harness_setup or []
    elif step == "check":
        cmds = cfg.harness_check or []
    else:
        raise SystemExit(f"Unknown harness step: {step}")

    for c in cmds:
        run(shell_cmd(c), cwd=ws_path, env=env, capture=False)
    return True
