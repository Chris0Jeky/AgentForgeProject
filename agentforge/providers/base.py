from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Protocol

@dataclass(frozen=True)
class RunResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    returncode: Optional[int] = None


class ProviderFailure(RuntimeError):
    def __init__(self, provider: str, result: RunResult):
        self.provider = provider
        self.returncode = result.returncode
        self.stderr = result.stderr[:2000]
        super().__init__(f"Provider {provider} failed (exit {self.returncode}): {self.stderr}")

class Provider(Protocol):
    name: str

    def run(self, *, prompt: str, cwd: Path, env: Optional[Dict[str, str]]=None) -> RunResult:
        ...
