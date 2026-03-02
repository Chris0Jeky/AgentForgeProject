from pathlib import Path

import pytest

from agentforge.core.config import load_repo_config


def test_load_repo_config_requires_files(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        load_repo_config(tmp_path)


def test_load_repo_config_reads_values_and_defaults(tmp_path: Path) -> None:
    af = tmp_path / ".agentforge"
    af.mkdir(parents=True)
    (af / "config.toml").write_text(
        'repo = "owner/repo"\n'
        'default_base_ref = "origin/main"\n'
        'worktrees_dir = ".worktrees"\n'
        'poll_interval_sec = 30\n',
        encoding="utf-8",
    )
    (af / "policy.toml").write_text(
        'mode = "fast"\n'
        'allowed_comment_authors = ["alice"]\n'
        "deny_forks = true\n",
        encoding="utf-8",
    )

    cfg, pol = load_repo_config(tmp_path)

    assert cfg.repo == "owner/repo"
    assert cfg.default_base_ref == "origin/main"
    assert cfg.worktrees_dir == ".worktrees"
    assert cfg.poll_interval_sec == 30
    assert pol.mode == "fast"
    assert pol.allowed_comment_authors == ["alice"]
    assert pol.deny_forks is True
