import pytest

from agentforge.core import workflow
from agentforge.core.config import Policy, RepoConfig
from agentforge.core.locks import acquire_lock, list_locks, release_lock
from agentforge.core.workspace import Workspace


@pytest.fixture
def workflow_env(tmp_path, monkeypatch):
    cfg = RepoConfig()
    ws = Workspace("a1", "issue-16", str(tmp_path), "af/a1/issue-16", 0)
    monkeypatch.setattr(workflow, "_find_ws", lambda *a: ws)
    return cfg, ws


def execute(root, cfg):
    return workflow.run_workflow(root=root, cfg=cfg, pol=Policy(), agent="a1", task="issue-16",
                                 workflow="test", log_json=False)


@pytest.mark.parametrize("failure", ["agent", "harness", "pr", "missing_type", "success"])
def test_workflow_scoped_lock_released_on_every_terminal_outcome(tmp_path, monkeypatch, workflow_env, failure):
    cfg, ws = workflow_env
    steps = [{"type": "lock", "group": "repo"}, {} if failure == "missing_type" else {"type": failure}]
    if failure == "success":
        steps[-1] = {"type": "note", "message": "done"}
    monkeypatch.setattr(workflow, "load_workflows", lambda _: {"test": steps})
    monkeypatch.setattr(workflow, "run_agent_role", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("agent failed")))
    monkeypatch.setattr(workflow, "run_harness_step", lambda **kw: False)
    monkeypatch.setattr(workflow, "create_pr", lambda **kw: (_ for _ in ()).throw(RuntimeError("PR failed")))
    summary = execute(tmp_path, cfg)
    assert list_locks(root=tmp_path, cfg=cfg) == []
    assert all(r.ok for r in summary.results) == (failure == "success")


def test_overlapping_same_identity_is_blocked_and_serial_resume_works(tmp_path, monkeypatch, workflow_env):
    cfg, ws = workflow_env
    monkeypatch.setattr(workflow, "load_workflows", lambda _: {"test": [
        {"type": "lock", "group": "repo"}, {"type": "agent"}]})
    calls = []

    def agent(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            nested = execute(tmp_path, cfg)
            assert not all(r.ok for r in nested.results)
            assert len(list_locks(root=tmp_path, cfg=cfg)) == 1

    monkeypatch.setattr(workflow, "run_agent_role", agent)
    assert all(r.ok for r in execute(tmp_path, cfg).results)
    assert calls == [1]
    assert all(r.ok for r in execute(tmp_path, cfg).results)
    assert calls == [1, 1]


def test_sticky_and_foreign_locks_are_preserved(tmp_path, monkeypatch, workflow_env):
    cfg, ws = workflow_env
    acquire_lock(root=tmp_path, cfg=cfg, group="foreign", agent="b", task="other")
    monkeypatch.setattr(workflow, "load_workflows", lambda _: {"test": [
        {"type": "lock", "group": "sticky", "sticky": True},
        {"type": "lock", "group": "foreign"}]})
    assert not all(r.ok for r in execute(tmp_path, cfg).results)
    assert {li.group for li in list_locks(root=tmp_path, cfg=cfg)} == {"sticky", "foreign"}


def test_cleanup_cannot_release_a_successor_and_reports_recovery(tmp_path, monkeypatch, workflow_env):
    cfg, ws = workflow_env
    monkeypatch.setattr(workflow, "load_workflows", lambda _: {"test": [
        {"type": "lock", "group": "repo"}, {"type": "agent"}]})

    def replace_owner(*a, **kw):
        release_lock(root=tmp_path, cfg=cfg, group="repo", force=True)
        acquire_lock(root=tmp_path, cfg=cfg, group="repo", agent="a1", task="issue-16")
        raise RuntimeError("original failure")

    monkeypatch.setattr(workflow, "run_agent_role", replace_owner)
    summary = execute(tmp_path, cfg)
    assert any(not r.ok and "original failure" in r.message for r in summary.results)
    assert any(not r.ok and r.step_type == "lock.cleanup" for r in summary.results)
    assert list_locks(root=tmp_path, cfg=cfg)[0].task == "issue-16"
