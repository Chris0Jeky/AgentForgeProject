from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agentforge.core.utils import CommandError
from agentforge.providers.codex_cli import CodexCliProvider


def test_build_exec_cmd_for_cmd_launcher() -> None:
    cmd = CodexCliProvider._build_exec_cmd(r"C:\Users\me\AppData\Roaming\npm\codex.cmd", "hello")
    assert cmd[:3] == ["cmd", "/c", r"C:\Users\me\AppData\Roaming\npm\codex.cmd"]
    assert cmd[3:] == ["exec", "hello"]


def test_build_exec_cmd_for_exe_launcher() -> None:
    cmd = CodexCliProvider._build_exec_cmd(r"C:\tools\codex.exe", "hello")
    assert cmd == [r"C:\tools\codex.exe", "exec", "hello"]


def test_run_returns_not_found_when_missing() -> None:
    p = CodexCliProvider()
    with patch("agentforge.providers.codex_cli.which", return_value=None):
        res = p.run(prompt="x", cwd=Path("."), env=None)
    assert res.ok is False
    assert "not found" in (res.stderr or "").lower()


def test_run_uses_resolved_binary() -> None:
    p = CodexCliProvider()
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return (0, "", "")

    with patch("agentforge.providers.codex_cli.which", side_effect=[r"C:\tools\codex.cmd", None, None]), patch(
        "agentforge.providers.codex_cli.run", side_effect=_fake_run
    ):
        res = p.run(prompt="x", cwd=Path("."), env=None)
    assert res.ok is True
    assert calls and calls[0][:3] == ["cmd", "/c", r"C:\tools\codex.cmd"]


def test_run_returns_error_on_command_failure() -> None:
    p = CodexCliProvider()
    err = CommandError(["codex", "exec", "x"], 1, "", "boom")

    with patch("agentforge.providers.codex_cli.which", side_effect=[r"C:\tools\codex.exe", None, None]), patch(
        "agentforge.providers.codex_cli.run", side_effect=err
    ):
        res = p.run(prompt="x", cwd=Path("."), env=None)
    assert res.ok is False
    assert "boom" in (res.stderr or "")


def test_inject_git_safe_directory_env_appends_entry() -> None:
    env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "x"}
    CodexCliProvider._inject_git_safe_directory(env, Path(r"C:\repo\ws"))
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_1"] == "safe.directory"
    assert env["GIT_CONFIG_VALUE_1"] == "C:/repo/ws"
