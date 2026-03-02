from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from agentforge.core.utils import run, CommandError, shell_cmd
from .base import RunResult

class ShellProvider:
    """A provider that runs a shell command as the 'agent'.

    Useful for:
    - integrating with other tools (aider, goose, custom scripts)
    - running local models
    - debugging the orchestrator

    You pass the full command line as the prompt (executed in an available shell).
    """
    name = "shell"

    def run(self, *, prompt: str, cwd: Path, env: Optional[Dict[str, str]]=None) -> RunResult:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        try:
            run(shell_cmd(prompt), cwd=cwd, env=merged, capture=False)
            return RunResult(ok=True)
        except CommandError as e:
            return RunResult(ok=False, stdout=e.stdout, stderr=e.stderr)
