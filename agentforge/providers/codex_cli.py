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
        codex_bin = self._resolve_codex_bin()
        if codex_bin is None:
            return RunResult(ok=False, stderr="codex CLI not found on PATH")

        merged = os.environ.copy()
        if env:
            merged.update(env)

        # Non-interactive: codex exec "..."
        # Keep capture minimal to avoid huge memory use; use check=False pattern here
        cmd = self._build_exec_cmd(codex_bin, prompt)
        try:
            run(cmd, cwd=cwd, env=merged, capture=False)
            return RunResult(ok=True)
        except CommandError as e:
            return RunResult(ok=False, stdout=e.stdout, stderr=e.stderr)

    @staticmethod
    def _resolve_codex_bin() -> Optional[str]:
        # Prefer explicit Windows launchers first, then generic name.
        return which("codex.cmd") or which("codex.exe") or which("codex")

    @staticmethod
    def _build_exec_cmd(codex_bin: str, prompt: str) -> list[str]:
        lower = codex_bin.lower()
        if lower.endswith(".cmd") or lower.endswith(".bat"):
            return ["cmd", "/c", codex_bin, "exec", prompt]
        return [codex_bin, "exec", prompt]
