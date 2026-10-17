from pathlib import Path
from types import SimpleNamespace

import pytest

from agentforge.core import workspace
from agentforge.core.state import load_state, save_state
from workspace_test_support import Interrupted, setup_workspace


def test_exhausted_pool_creates_no_worktree_or_branch(tmp_path, monkeypatch):
    cfg, pol, state, git = setup_workspace(tmp_path, monkeypatch)
    workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    branches, trees = git.branches.copy(), git.worktrees.copy()
    with pytest.raises(SystemExit, match="No free ports"):
        workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="b", task="task")
    assert git.branches == branches and git.worktrees == trees


@pytest.mark.parametrize("failure", ["reserve", "env", "activate", "crash_after_add", "crash_after_branch"])
def test_spawn_failure_is_journaled_and_retryable(tmp_path, monkeypatch, failure):
    cfg, pol, state, git = setup_workspace(tmp_path, monkeypatch)
    save, write = workspace.save_state, Path.write_text

    def fail_save(path, value):
        record = value["workspaces"]["a:task"]
        if failure == "reserve" or (failure == "activate" and record.get("status") == "active"):
            raise OSError("state publication failed")
        save(path, value)

    def fail_env(path, *args, **kwargs):
        if path.name == ".agentforge.env":
            raise OSError("env write failed")
        return write(path, *args, **kwargs)

    if failure in ("reserve", "activate"):
        monkeypatch.setattr(workspace, "save_state", fail_save)
    if failure == "env":
        monkeypatch.setattr(Path, "write_text", fail_env)
    git.interrupt_add = failure == "crash_after_add"
    git.interrupt_branch = failure == "crash_after_branch"
    with pytest.raises((OSError, Interrupted)):
        workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    saved = load_state(state)
    if failure == "reserve":
        assert not git.branches and not git.worktrees and not saved["ports"]
    else:
        assert saved["workspaces"]["a:task"]["status"] == "spawning"
        assert saved["ports"]
        assert not workspace.list_workspaces(state)
        assert workspace.list_workspaces(state, include_pending=True)[0].status == "spawning"
        with pytest.raises(SystemExit, match="No free ports"):
            workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="b", task="other")
    monkeypatch.setattr(workspace, "save_state", save)
    monkeypatch.setattr(Path, "write_text", write)
    ws = workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    assert load_state(state)["workspaces"]["a:task"]["status"] == "active"
    assert Path(ws.path, ".agentforge.env").is_file()
    assert git.branches == {ws.branch} and len(git.worktrees) == 1
    assert workspace.list_workspaces(state) == [ws]


def test_spawn_refuses_preexisting_unjournaled_worktree_or_branch(tmp_path, monkeypatch):
    cfg, pol, state, git = setup_workspace(tmp_path, monkeypatch)
    git.branches.add("af/a/task")
    with pytest.raises(SystemExit, match="branch exists"):
        workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    assert not load_state(state)["ports"] and not git.worktrees


def test_pending_spawn_can_be_deliberately_removed(tmp_path, monkeypatch):
    cfg, pol, state, git = setup_workspace(tmp_path, monkeypatch)
    git.interrupt_add = True
    with pytest.raises(Interrupted):
        workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    workspace.remove_workspace(tmp_path, cfg, state, agent="a", task="task", delete_branch=True)
    assert load_state(state)["workspaces"] == load_state(state)["ports"] == {}
    assert not git.worktrees and not git.branches


@pytest.mark.parametrize("command", ["cmd_list", "cmd_status"])
def test_pending_workspace_is_visible_in_cli(tmp_path, monkeypatch, capsys, command):
    from agentforge import cli

    cfg, pol, state, git = setup_workspace(tmp_path, monkeypatch)
    git.interrupt_add = True
    with pytest.raises(Interrupted):
        workspace.spawn_workspace(tmp_path, cfg, pol, state, agent="a", task="task")
    monkeypatch.setattr(cli, "find_repo_root", lambda *_: tmp_path)
    monkeypatch.setattr(cli, "load_repo_config", lambda _: (cfg, pol))
    monkeypatch.setattr(cli, "state_paths", lambda *_: (state, tmp_path))
    assert getattr(cli, command)(SimpleNamespace(repo=None)) == 0
    output = capsys.readouterr().out
    assert "a:task" in output and "spawning" in output


def test_pending_workspace_is_visible_in_status_api(tmp_path, monkeypatch):
    import json
    import tempfile

    from agentforge.core import server
    from server_test_support import dashboard, request, TOKEN

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(server, "docker_mcp_available", lambda: False)
    monkeypatch.setattr(server, "load_workflows", lambda _: {})
    with dashboard() as (root, cfg, port):
        state = root / cfg.state_dir / "state.json"
        state.parent.mkdir(parents=True)
        save_state(state, {"ports": {}, "workspaces": {"a:task": {
            "agent": "a", "task": "task", "path": str(root / "pending"),
            "branch": "af/a/task", "port": 8081, "status": "spawning",
        }}})
        status, body = request(port, "GET", "/api/status", headers={"Authorization": "Bearer " + TOKEN})
        assert status == 200
        assert json.loads(body)["workspaces"][0]["status"] == "spawning"
