from types import SimpleNamespace

import pytest

from agentforge.core.config import Policy, RepoConfig
from agentforge.core.runner import run_agent_role
from agentforge.core.workspace import Workspace
from agentforge.providers.base import RunResult


def test_provider_failure_is_catchable_and_bounded(tmp_path, monkeypatch):
    from agentforge.core import runner

    monkeypatch.setattr(runner, "get_provider", lambda _: SimpleNamespace(
        run=lambda **kw: RunResult(ok=False, stderr="failed" * 1000)))
    ws = Workspace("a1", "issue-23", str(tmp_path), "af/a1/issue-23", 0)
    with pytest.raises(RuntimeError, match="Provider mock failed") as caught:
        run_agent_role(tmp_path, RepoConfig(), Policy(), ws, provider="mock",
                       role="fix", prompt="fix", auto_commit=False, auto_push=False)
    assert caught.value.provider == "mock"
    assert len(caught.value.stderr) <= 2000


def test_failed_provider_produces_workflow_summary_and_releases_lock(tmp_path, monkeypatch):
    from agentforge.core import runner, workflow
    from agentforge.core.locks import list_locks

    ws = Workspace("a1", "issue-23", str(tmp_path), "af/a1/issue-23", 0)
    monkeypatch.setattr(runner, "get_provider", lambda _: SimpleNamespace(
        run=lambda **kw: RunResult(ok=False, stderr="provider exited", returncode=7)))
    monkeypatch.setattr(workflow, "_find_ws", lambda *a: ws)
    monkeypatch.setattr(workflow, "load_workflows", lambda _: {"test": [
        {"type": "lock", "group": "repo"}, {"type": "agent"}]})
    events = []
    summary = workflow.run_workflow(root=tmp_path, cfg=RepoConfig(), pol=Policy(), agent="a1",
                                    task="issue-23", workflow="test", event_cb=events.append)
    assert not summary.results[-1].ok and "exit 7" in summary.results[-1].message
    assert list_locks(root=tmp_path, cfg=RepoConfig()) == []
    assert events[-1]["type"] == "workflow_end"
