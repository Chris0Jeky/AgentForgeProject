from pathlib import Path

import pytest

from agentforge.core import workspace
from agentforge.core.config import Policy, RepoConfig
from agentforge.core.state import load_state, state_paths
from agentforge.core.utils import CommandError, out, run
from workspace_test_support import Interrupted


def test_real_git_reconciles_interrupted_spawn_and_removal(tmp_path, monkeypatch):
    root = tmp_path / "repo with spaces é"
    root.mkdir()
    run(["git", "init", "-q"], cwd=root, capture=True)
    (root / ".gitignore").write_text(".worktrees/\n.agentforge/\n.agentforge.env\n.envrc\nset-env.ps1\n", encoding="utf-8")
    run(["git", "add", ".gitignore"], cwd=root, capture=True)
    run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"], cwd=root, capture=True)
    cfg = RepoConfig(default_base_ref="HEAD", port_start=8081, port_end=8081)
    state, _ = state_paths(root, cfg)
    original_run = workspace.run

    def crash_after_add(cmd, **kwargs):
        result = original_run(cmd, **kwargs)
        if cmd[1:3] == ["worktree", "add"]:
            raise Interrupted()
        return result

    monkeypatch.setattr(workspace, "run", crash_after_add)
    with pytest.raises(Interrupted):
        workspace.spawn_workspace(root, cfg, Policy(), state, agent="a", task="task")
    assert load_state(state)["workspaces"]["a:task"]["status"] == "spawning"
    monkeypatch.setattr(workspace, "run", original_run)
    ws = workspace.spawn_workspace(root, cfg, Policy(), state, agent="a", task="task")
    assert Path(ws.path, ".agentforge.env").is_file()
    assert out(["git", "branch", "--show-current"], cwd=Path(ws.path)) == ws.branch

    human_file = Path(ws.path, "human.txt")
    human_file.write_text("preserve", encoding="utf-8")
    with pytest.raises(CommandError):
        workspace.remove_workspace(root, cfg, state, agent="a", task="task", delete_branch=True)
    assert human_file.read_text(encoding="utf-8") == "preserve"
    assert load_state(state)["ports"]
    human_file.unlink()

    original_save = workspace.save_state

    def crash_before_publication(path, value):
        if not value["workspaces"]:
            raise Interrupted()
        original_save(path, value)

    monkeypatch.setattr(workspace, "save_state", crash_before_publication)
    with pytest.raises(Interrupted):
        workspace.remove_workspace(root, cfg, state, agent="a", task="task")
    assert not Path(ws.path).exists()
    assert load_state(state)["workspaces"]["a:task"]["status"] == "removing"
    monkeypatch.setattr(workspace, "save_state", original_save)
    workspace.remove_workspace(root, cfg, state, agent="a", task="task")
    assert load_state(state)["workspaces"] == load_state(state)["ports"] == {}
    assert not out(["git", "for-each-ref", "--format=%(refname)", "refs/heads/af/"], cwd=root)
