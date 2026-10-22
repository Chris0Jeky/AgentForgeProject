from __future__ import annotations

import subprocess

import pytest

from agentforge.core.runner import (
    _status_changed_paths_from_porcelain,
    _violating_paths,
    _working_tree_changed_files,
)


def test_status_changed_paths_from_porcelain_parses_common_entries() -> None:
    porcelain = (
        " M agentforge/core/runner.py\0"
        "?? docs/codex-smoke.md\0"
        "R  new/path.txt\0old/path.txt\0"
    )
    assert _status_changed_paths_from_porcelain(porcelain) == [
        "agentforge/core/runner.py",
        "docs/codex-smoke.md",
        "new/path.txt",
        "old/path.txt",
    ]


def test_violating_paths_reports_only_out_of_scope() -> None:
    changed = [
        "docs/codex-smoke.md",
        "docs/notes.md",
        "agentforge/core/runner.py",
    ]
    allowed = ["docs/codex-smoke.md", "docs/notes.md"]
    assert _violating_paths(changed, allowed) == ["agentforge/core/runner.py"]


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-q", "--template=")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "source.txt").write_text("base\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_surgical_paths_include_both_sides_of_a_rename(repository):
    git(repository, "mv", "source.txt", "allowed.txt")
    changed = _working_tree_changed_files(repository)
    assert _violating_paths(changed, ["allowed.txt"]) == ["source.txt"]


@pytest.mark.parametrize("name", ["bad -> allowed.txt", "space name.txt", "caf\u00e9.txt"])
def test_surgical_paths_preserve_literal_filenames(repository, name):
    (repository / name).write_text("new\n")
    changed = _working_tree_changed_files(repository)
    assert changed == [name]
    assert _violating_paths(changed, ["allowed.txt"]) == [name]


def test_surgical_paths_expand_untracked_directories(repository):
    directory = repository / "docs"
    directory.mkdir()
    (directory / "allowed.txt").write_text("new\n")
    assert _working_tree_changed_files(repository) == ["docs/allowed.txt"]


def test_surgical_paths_keep_first_unstaged_filename(repository):
    (repository / "source.txt").write_text("changed\n")
    assert _working_tree_changed_files(repository) == ["source.txt"]
