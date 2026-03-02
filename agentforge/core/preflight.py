from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .utils import which

@dataclass(frozen=True)
class ToolStatus:
    name: str
    required: bool
    found: bool
    hint: Optional[str] = None

def check_tools(*, require_gh: bool=False, require_docker: bool=False, require_codex: bool=False) -> List[ToolStatus]:
    tools: List[ToolStatus] = []
    tools.append(ToolStatus("git", True, which("git") is not None, hint="Install git"))
    if require_gh:
        tools.append(ToolStatus("gh", True, which("gh") is not None, hint="Install GitHub CLI and run `gh auth login`"))
    else:
        tools.append(ToolStatus("gh", False, which("gh") is not None, hint="Optional: GitHub CLI"))
    if require_docker:
        tools.append(ToolStatus("docker", True, which("docker") is not None, hint="Install Docker Desktop / Engine"))
    else:
        tools.append(ToolStatus("docker", False, which("docker") is not None, hint="Optional: Docker"))
    if require_codex:
        tools.append(ToolStatus("codex", True, which("codex") is not None, hint="Install Codex CLI"))
    else:
        tools.append(ToolStatus("codex", False, which("codex") is not None, hint="Optional: Codex CLI"))
    return tools

def print_preflight(status: List[ToolStatus]) -> None:
    print("Preflight:")
    ok = True
    for t in status:
        mark = "OK" if t.found else ("MISSING" if t.required else "absent")
        print(f"- {t.name}: {mark}")
        if t.required and not t.found:
            ok = False
            if t.hint:
                print(f"    hint: {t.hint}")
    if not ok:
        raise SystemExit("Missing required tools; fix preflight failures and re-run.")
