from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agentforge.core.config import _normalize_repo_root_path


def test_normalize_cygdrive_windows() -> None:
    with patch("agentforge.core.config.os.name", "nt"):
        p = _normalize_repo_root_path("/cygdrive/c/Users/jekyt/source/AgentForge/AgentForgeProject")
    assert p == Path(r"C:/Users/jekyt/source/AgentForge/AgentForgeProject")


def test_normalize_msys_windows() -> None:
    with patch("agentforge.core.config.os.name", "nt"):
        p = _normalize_repo_root_path("/c/Users/jekyt/source/AgentForge/AgentForgeProject")
    assert p == Path(r"C:/Users/jekyt/source/AgentForge/AgentForgeProject")


def test_no_normalize_non_windows() -> None:
    raw = "/home/user/project"
    with patch("agentforge.core.config.os.name", "posix"):
        p = _normalize_repo_root_path(raw)
    assert str(p).replace("\\", "/") == raw
