from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Protocol

@dataclass(frozen=True)
class RunResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""

class Provider(Protocol):
    name: str

    def run(self, *, prompt: str, cwd: Path, env: Optional[Dict[str, str]]=None) -> RunResult:
        ...
