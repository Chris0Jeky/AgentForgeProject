from __future__ import annotations

from unittest.mock import patch

from agentforge.core.utils import shell_cmd


def _which_map(mapping: dict[str, bool]):
    def _inner(name: str):
        return name if mapping.get(name, False) else None

    return _inner


def test_shell_cmd_windows_prefers_pwsh() -> None:
    with patch("agentforge.core.utils.os.name", "nt"), patch(
        "agentforge.core.utils.which",
        side_effect=_which_map(
            {
                "bash": True,
                "pwsh": True,
                "powershell": True,
                "sh": True,
            }
        ),
    ):
        cmd = shell_cmd("echo hi")
    assert cmd[:3] == ["pwsh", "-NoProfile", "-Command"]


def test_shell_cmd_windows_falls_back_to_bash() -> None:
    with patch("agentforge.core.utils.os.name", "nt"), patch(
        "agentforge.core.utils.which",
        side_effect=_which_map(
            {
                "bash": True,
                "pwsh": False,
                "powershell": False,
                "sh": False,
            }
        ),
    ):
        cmd = shell_cmd("echo hi")
    assert cmd[:2] == ["bash", "-lc"]


def test_shell_cmd_posix_prefers_bash() -> None:
    with patch("agentforge.core.utils.os.name", "posix"), patch(
        "agentforge.core.utils.which",
        side_effect=_which_map(
            {
                "bash": True,
                "pwsh": True,
                "powershell": True,
                "sh": True,
            }
        ),
    ):
        cmd = shell_cmd("echo hi")
    assert cmd[:2] == ["bash", "-lc"]

