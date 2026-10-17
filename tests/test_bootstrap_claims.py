from types import SimpleNamespace

import pytest

from agentforge.core import bootstrap
from agentforge.core.config import Policy, RepoConfig
from agentforge.core.queue import Issue
from agentforge.core.state import load_state, state_paths
from agentforge.core.workspace import Workspace


@pytest.fixture
def claimed_queue(tmp_path, monkeypatch):
    cfg = RepoConfig(repo="fixture/repo", default_provider="mock")
    issue = Issue(21, "claim regression", "https://example.invalid/21", [cfg.queue_label])
    ws = Workspace("a1", "issue-21", str(tmp_path / "ws"), "af/a1/issue-21", 0)
    labels = []
    monkeypatch.setattr(bootstrap, "list_issues", lambda **kw: [issue])
    monkeypatch.setattr(bootstrap, "load_lock_groups", lambda _: {})
    monkeypatch.setattr(bootstrap, "select_lock_group_for_issue", lambda *a, **kw: None)
    monkeypatch.setattr(bootstrap, "check_tools", lambda **kw: [])
    monkeypatch.setattr(bootstrap, "list_workspaces", lambda _: [ws])
    monkeypatch.setattr(bootstrap, "view_issue_body", lambda _: "fix")
    monkeypatch.setattr(bootstrap, "claim_issue", lambda **kw: labels.append(kw))
    return cfg, ws, labels


@pytest.mark.parametrize("failure", ["before_workflow", "agent", "harness", "pr", "crash"])
def test_failed_claim_remains_discoverable_without_duplicate_work(tmp_path, monkeypatch, claimed_queue, failure):
    cfg, ws, labels = claimed_queue
    calls = []

    def workflow(**kw):
        calls.append(kw)
        if failure == "crash":
            raise KeyboardInterrupt()
        if failure == "pr":
            raise RuntimeError("PR outcome unknown")
        return SimpleNamespace(results=[SimpleNamespace(ok=False, step_index=1, step_type=failure,
                                                        message="failed")], pr_url=None)

    monkeypatch.setattr(bootstrap, "run_workflow", workflow)
    if failure == "before_workflow":
        monkeypatch.setattr(bootstrap, "view_issue_body", lambda _: (_ for _ in ()).throw(OSError("offline")))
    args = dict(agents=["a1"], take=1, fast=True, claim=True, create_prs=True,
                draft_prs=True, run_daemon=False, event_cb=lambda ev: None)
    if failure == "crash":
        with pytest.raises(KeyboardInterrupt):
            bootstrap.run_bootstrap(tmp_path, cfg, Policy(), **args)
    else:
        bootstrap.run_bootstrap(tmp_path, cfg, Policy(), **args)
    assert labels == []
    st_file, _ = state_paths(tmp_path, cfg)
    receipt = load_state(st_file)["bootstrap_claims"]["21"]
    assert receipt["agent"] == "a1" and receipt["task"] == "issue-21"
    assert receipt["workspace"] == ws.path and receipt["attempt_id"]
    monkeypatch.setattr(bootstrap, "list_issues", lambda **kw: [])
    plan = bootstrap.build_plan_from_queue(tmp_path, cfg, agents=["different"])
    assert [(it.issue_number, it.agent) for it in plan] == [(21, "a1")]
    args["claim"] = False
    bootstrap.run_bootstrap(tmp_path, cfg, Policy(), **args)
    assert len(calls) == (0 if failure == "before_workflow" else 1)
    assert load_state(st_file)["bootstrap_claims"]["21"]["state"] == "reconciliation_required"


def test_success_moves_labels_only_after_reviewable_outcome(tmp_path, monkeypatch, claimed_queue):
    cfg, ws, labels = claimed_queue

    def workflow(**kw):
        assert labels == []
        return SimpleNamespace(results=[SimpleNamespace(ok=True)], pr_url="https://example.invalid/pr/1")

    monkeypatch.setattr(bootstrap, "run_workflow", workflow)
    bootstrap.run_bootstrap(tmp_path, cfg, Policy(), agents=["a1"], take=1, fast=True, claim=True,
                            create_prs=True, draft_prs=True, run_daemon=False, event_cb=lambda ev: None)
    assert len(labels) == 1 and labels[0]["number"] == 21
    st_file, _ = state_paths(tmp_path, cfg)
    assert load_state(st_file)["bootstrap_claims"]["21"]["state"] == "completed"


def test_label_transport_failure_retries_only_the_label_move(tmp_path, monkeypatch, claimed_queue):
    cfg, ws, labels = claimed_queue
    calls = []
    monkeypatch.setattr(bootstrap, "run_workflow", lambda **kw: calls.append(1) or SimpleNamespace(
        results=[SimpleNamespace(ok=True)], pr_url="https://example.invalid/pr/1"))

    def claim_issue(**kw):
        labels.append(kw)
        if len(labels) == 1:
            raise OSError("label response lost")

    monkeypatch.setattr(bootstrap, "claim_issue", claim_issue)
    args = dict(agents=["a1"], take=1, fast=True, claim=True, create_prs=True,
                draft_prs=True, run_daemon=False, event_cb=lambda ev: None)
    bootstrap.run_bootstrap(tmp_path, cfg, Policy(), **args)
    st_file, _ = state_paths(tmp_path, cfg)
    assert load_state(st_file)["bootstrap_claims"]["21"]["state"] == "labels_pending"
    bootstrap.run_bootstrap(tmp_path, cfg, Policy(), **args)
    assert len(calls) == 1 and len(labels) == 2
    assert load_state(st_file)["bootstrap_claims"]["21"]["state"] == "completed"
