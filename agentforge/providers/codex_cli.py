from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from agentforge.core.utils import which, run, CommandError
from .base import RunResult

class CodexCliProvider:
    """Runs OpenAI Codex CLI in non-interactive mode via `codex exec`.

    This adapter intentionally shells out, so AgentForge doesn't vendor SDKs.
    """
    name = "codex_cli"

    def run(self, *, prompt: str, cwd: Path, env: Optional[Dict[str, str]]=None) -> RunResult:
        if which("codex") is None:
            return RunResult(ok=False, stderr="codex CLI not found on PATH")

        merged = os.environ.copy()
        if env:
            merged.update(env)

        # Non-interactive: codex exec "..."
        # Keep capture minimal to avoid huge memory use; use check=False pattern here
        try:
            run(["codex", "exec", prompt], cwd=cwd, env=merged, capture=False)
            return RunResult(ok=True)
        except CommandError as e:
            return RunResult(ok=False, stdout=e.stdout, stderr=e.stderr)
