import pytest
from pathlib import Path

from agentforge.core import workspace
from agentforge.core.state import load_state
from workspace_test_support import Interrupted, setup_workspace


def test_failed_removal_retains_record_and_port_until_retry(tmp_path, monkeypatch):
    cfg, pol, state, git = setup_workspace(tmp_path, monkeypatch)
    ws = workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    git.fail_remove = True
    with pytest.raises(RuntimeError, match="git removal failed"):
        workspace.remove_workspace(tmp_path, cfg, state, agent="a", task="task")
    saved = load_state(state)
    assert saved["workspaces"]["a:task"]["path"] == ws.path
    assert saved["workspaces"]["a:task"]["status"] == "removing"
    assert str(ws.port) in saved["ports"]
    with pytest.raises(SystemExit, match="No free ports"):
        workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="b", task="other")
    git.fail_remove = False
    workspace.remove_workspace(tmp_path, cfg, state, agent="a", task="task")
    assert load_state(state)["workspaces"] == load_state(state)["ports"] == {}
    assert not git.worktrees


def test_removal_retries_after_git_succeeds_before_state_publication(tmp_path, monkeypatch):
    cfg, pol, state, git = setup_workspace(tmp_path, monkeypatch)
    workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    save = workspace.save_state

    def interrupt_publication(path, value):
        if not value["workspaces"]:
            raise Interrupted()
        save(path, value)

    monkeypatch.setattr(workspace, "save_state", interrupt_publication)
    with pytest.raises(Interrupted):
        workspace.remove_workspace(tmp_path, cfg, state, agent="a", task="task", delete_branch=True)
    assert load_state(state)["workspaces"]["a:task"]["status"] == "removing"
    assert load_state(state)["ports"]
    assert not git.worktrees
    monkeypatch.setattr(workspace, "save_state", save)
    workspace.remove_workspace(tmp_path, cfg, state, agent="a", task="task")
    assert load_state(state)["workspaces"] == load_state(state)["ports"] == {}
    assert not git.branches


def test_removal_refuses_a_replaced_worktree(tmp_path, monkeypatch):
    cfg, pol, state, git = setup_workspace(tmp_path, monkeypatch)
    ws = workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    git.worktrees[Path(ws.path).resolve()] = "someone-else"
    before = git.commands.copy()
    with pytest.raises(SystemExit, match="does not match journal"):
        workspace.remove_workspace(tmp_path, cfg, state, agent="a", task="task")
    assert git.commands == before
    assert Path(ws.path).exists()
    assert str(ws.port) in load_state(state)["ports"]


def test_refused_branch_deletion_is_not_remembered_by_a_later_plain_removal(tmp_path, monkeypatch):
    cfg, pol, state, git = setup_workspace(tmp_path, monkeypatch)
    ws = workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    git.fail_remove = True
    with pytest.raises(RuntimeError, match="git removal failed"):
        workspace.remove_workspace(tmp_path, cfg, state, agent="a", task="task", delete_branch=True)
    git.fail_remove = False
    workspace.remove_workspace(tmp_path, cfg, state, agent="a", task="task")
    assert ws.branch in git.branches  # unpushed work on the branch survives a plain rm
