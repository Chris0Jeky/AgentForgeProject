from __future__ import annotations

from unittest.mock import patch

from agentforge.core.utils import shell_cmd


def _which_from_available(available: set[str]):
    def _which(exe: str):
        return exe if exe in available else None

    return _which


def test_shell_cmd_windows_prefers_pwsh_over_bash() -> None:
    with patch("agentforge.core.utils.os.name", "nt"):
        with patch(
            "agentforge.core.utils.which",
            side_effect=_which_from_available({"pwsh", "powershell", "bash", "sh"}),
        ):
            cmd = shell_cmd("echo hello")
    assert cmd[:3] == ["pwsh", "-NoProfile", "-Command"]
    assert cmd[3] == "echo hello"


def test_shell_cmd_windows_falls_back_to_bash() -> None:
    with patch("agentforge.core.utils.os.name", "nt"):
        with patch(
            "agentforge.core.utils.which",
            side_effect=_which_from_available({"bash", "sh"}),
        ):
            cmd = shell_cmd("echo hello")
    assert cmd[:2] == ["bash", "-lc"]
    assert cmd[2] == "echo hello"


def test_shell_cmd_non_windows_prefers_bash_over_pwsh() -> None:
    with patch("agentforge.core.utils.os.name", "posix"):
        with patch(
            "agentforge.core.utils.which",
            side_effect=_which_from_available({"pwsh", "powershell", "bash", "sh"}),
        ):
            cmd = shell_cmd("echo hello")
    assert cmd[:2] == ["bash", "-lc"]
    assert cmd[2] == "echo hello"
