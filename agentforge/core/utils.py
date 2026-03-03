from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

class CommandError(RuntimeError):
    def __init__(self, cmd: List[str], returncode: int, stdout: str, stderr: str):
        super().__init__(f"Command failed ({returncode}): {' '.join(cmd)}\n{stderr.strip()}")
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

def which(exe: str) -> Optional[str]:
    return shutil.which(exe)

def shell_cmd(command: str) -> List[str]:
    """Return a command list that runs `command` in an available shell.

    Priority is platform-aware:
      - Windows: pwsh, powershell, bash, sh
      - Non-Windows: bash, sh, pwsh, powershell

    If none exist, raise a clear error.
    """
    if os.name == "nt":
        candidates = [
            ("pwsh", ["-NoProfile", "-Command"]),
            ("powershell", ["-NoProfile", "-Command"]),
            ("bash", ["-lc"]),
            ("sh", ["-lc"]),
        ]
    else:
        candidates = [
            ("bash", ["-lc"]),
            ("sh", ["-lc"]),
            ("pwsh", ["-NoProfile", "-Command"]),
            ("powershell", ["-NoProfile", "-Command"]),
        ]

    for exe, args in candidates:
        if which(exe):
            return [exe, *args, command]

    raise RuntimeError("No supported shell found (need bash/sh or PowerShell).")

def run(cmd: List[str], *, cwd: Optional[Path]=None, env: Optional[Dict[str, str]]=None, capture: bool=False) -> Tuple[int, str, str]:
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=capture,
    )
    out = p.stdout or ""
    err = p.stderr or ""
    if p.returncode != 0:
        raise CommandError(cmd, p.returncode, out, err)
    return p.returncode, out, err

def out(cmd: List[str], *, cwd: Optional[Path]=None, env: Optional[Dict[str, str]]=None) -> str:
    _, stdout, _ = run(cmd, cwd=cwd, env=env, capture=True)
    return stdout.strip()

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def atomic_write_text(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
