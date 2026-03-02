from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from .base import RunResult

class MockProvider:
    """A deterministic provider for tests and demos."""
    name = "mock"

    def run(self, *, prompt: str, cwd: Path, env: Optional[Dict[str, str]]=None) -> RunResult:
        # Doesn't touch filesystem. Returns prompt as stdout.
        return RunResult(ok=True, stdout=f"[mock] would run in {cwd}:\n{prompt}\n")
