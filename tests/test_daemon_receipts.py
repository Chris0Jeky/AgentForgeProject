from types import SimpleNamespace

import pytest

from agentforge.core import daemon
from agentforge.core.config import Policy, RepoConfig
from agentforge.core.state import load_state
from agentforge.providers.base import RunResult
from agentforge.core.workspace import Workspace


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    cfg = RepoConfig(repo="fixture/repo")
    st_file = tmp_path / "state.json"
    comments = [{"id": cid, "body": "/agentforge fix change", "user": {"login": "owner"}}
                for cid in (10, 20)]
    sent = []
    monkeypatch.setattr(daemon, "list_open_prs", lambda: [{"number": 1}])
    monkeypatch.setattr(daemon, "pr_view", lambda _: SimpleNamespace(is_cross_repo=False))
    monkeypatch.setattr(daemon, "list_issue_comments", lambda *a: comments)
    monkeypatch.setattr(daemon, "is_allowed_commenter", lambda *a: True)
    monkeypatch.setattr(daemon, "post_pr_comment", lambda n, body: sent.append(body))
    monkeypatch.setattr("agentforge.core.lock_maintenance.maybe_maintain_sticky_locks", lambda *a: None)
    return cfg, st_file, comments, sent


def test_crash_after_dispatch_requires_reconciliation_without_reexecution(tmp_path, monkeypatch, inbox):
    cfg, st_file, comments, sent = inbox
    calls = []

    def crash(*args):
        calls.append(args[-2])
        raise KeyboardInterrupt()

    monkeypatch.setattr(daemon, "_handle_command", crash)
    with pytest.raises(KeyboardInterrupt):
        daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert load_state(st_file)["prs"]["1"].get("last_comment_id", 0) == 0
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    pr = load_state(st_file)["prs"]["1"]
    assert pr["commands"]["10"]["state"] == "reconciliation_required"
    assert pr["commands"]["20"]["state"] == "observed"
    assert len(calls) == 1
    assert "comment #10" in sent[-1]


def test_delivery_failure_retries_response_without_rerunning_command(tmp_path, monkeypatch, inbox):
    cfg, st_file, comments, sent = inbox
    calls = []
    monkeypatch.setattr(daemon, "_handle_command", lambda *a: calls.append(a[-2]) or "Fixed")
    monkeypatch.setattr(daemon, "post_pr_comment", lambda *a: (_ for _ in ()).throw(OSError("offline")))
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert len(calls) == 1
    assert load_state(st_file)["prs"]["1"].get("last_comment_id", 0) == 0
    monkeypatch.setattr(daemon, "post_pr_comment", lambda n, body: sent.append(body))
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert len(calls) == 2
    assert load_state(st_file)["prs"]["1"]["last_comment_id"] == 20
    assert all("comment #" in body for body in sent)


def test_per_pr_error_does_not_skip_later_pr(tmp_path, monkeypatch, inbox):
    cfg, st_file, comments, sent = inbox
    seen = []
    monkeypatch.setattr(daemon, "list_open_prs", lambda: [{"number": 1}, {"number": 2}])

    def view(number):
        seen.append(number)
        if number == 1:
            raise RuntimeError("bad PR")
        return SimpleNamespace(is_cross_repo=True)

    monkeypatch.setattr(daemon, "pr_view", view)
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert seen == [1, 2]
    assert "bad PR" in load_state(st_file)["prs"]["1"]["error"]


def test_crash_before_dispatch_preserves_observation(tmp_path, monkeypatch, inbox):
    cfg, st_file, comments, sent = inbox
    original = daemon.save_state

    def crash_after_observation(path, st):
        original(path, st)
        if st.get("prs", {}).get("1", {}).get("commands"):
            raise KeyboardInterrupt()

    monkeypatch.setattr(daemon, "save_state", crash_after_observation)
    with pytest.raises(KeyboardInterrupt):
        daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    monkeypatch.setattr(daemon, "save_state", original)
    calls = []
    monkeypatch.setattr(daemon, "_handle_command", lambda *a: calls.append(a[-2]) or "Done")
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert len(calls) == 2
    assert load_state(st_file)["prs"]["1"]["last_comment_id"] == 20


def test_crash_between_commands_only_reconciles_unknown_command(tmp_path, monkeypatch, inbox):
    cfg, st_file, comments, sent = inbox
    calls = []

    def handle(*a):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt()
        return "Done"

    monkeypatch.setattr(daemon, "_handle_command", handle)
    with pytest.raises(KeyboardInterrupt):
        daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert load_state(st_file)["prs"]["1"]["last_comment_id"] == 10
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert len(calls) == 2
    assert load_state(st_file)["prs"]["1"]["commands"]["20"]["state"] == "reconciliation_required"


def test_unknown_delivery_checks_comment_marker_before_reposting(tmp_path, monkeypatch, inbox):
    cfg, st_file, comments, sent = inbox
    calls = []
    monkeypatch.setattr(daemon, "_handle_command", lambda *a: calls.append(1) or "Done")

    def uncertain_delivery(n, body):
        comments.append({"id": 30, "body": body, "user": {"login": "bot"}})
        raise OSError("response lost")

    monkeypatch.setattr(daemon, "post_pr_comment", uncertain_delivery)
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    monkeypatch.setattr(daemon, "post_pr_comment", lambda n, body: sent.append(body))
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert len(calls) == 2 and len(sent) == 1
    assert "comment #20" in sent[0]


def test_provider_nonzero_records_failure_and_inspects_next_pr(tmp_path, monkeypatch, inbox):
    from agentforge.core import runner

    cfg, st_file, comments, sent = inbox
    monkeypatch.setattr(daemon, "list_open_prs", lambda: [{"number": 1}, {"number": 2}])
    monkeypatch.setattr(daemon, "pr_view", lambda _: SimpleNamespace(is_cross_repo=False, head_ref="af/a1/issue-23"))
    monkeypatch.setattr(daemon, "_find_workspace", lambda *a: Workspace(
        "a1", "issue-23", str(tmp_path), "af/a1/issue-23", 0))
    monkeypatch.setattr(runner, "get_provider", lambda _: SimpleNamespace(
        run=lambda **kw: RunResult(ok=False, stderr="nonzero", returncode=7)))
    monkeypatch.setattr(daemon, "list_issue_comments", lambda owner, name, number: comments[:1] if number == 1 else [
        {"id": 40, "body": "/agentforge status", "user": {"login": "owner"}}])
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    st = load_state(st_file)
    assert st["prs"]["1"]["commands"]["10"]["state"] == "reconciliation_required"
    assert "Fix failed" in sent[0] and "exit 7" in sent[0]
    assert st["prs"]["2"]["last_comment_id"] == 40


def test_active_dispatch_cannot_be_reentered(tmp_path, monkeypatch, inbox):
    cfg, st_file, comments, sent = inbox
    calls = []

    def handle(*a):
        calls.append(1)
        daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
        return "Done"

    monkeypatch.setattr(daemon, "_handle_command", handle)
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert len(calls) == 2
    assert load_state(st_file)["prs"]["1"]["last_comment_id"] == 20


def test_webhook_and_daemon_share_receipts(tmp_path, monkeypatch, inbox):
    import json
    from agentforge.core import webhook

    cfg, st_file, comments, sent = inbox
    monkeypatch.setattr(webhook, "is_allowed_commenter", lambda *a: True)
    monkeypatch.setattr(webhook, "list_issue_comments", lambda *a: comments)
    calls = []
    monkeypatch.setattr(daemon, "_handle_command", lambda *a: calls.append(1) or "Done")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"action": "created", "comment": comments[0],
                                 "issue": {"number": 1, "pull_request": {}}}), encoding="utf-8")
    webhook.handle_github_event_file(tmp_path, cfg, Policy(), st_file, event)
    daemon.run_daemon_once(tmp_path, cfg, Policy(), st_file)
    assert len(calls) == 2 and len(sent) == 2


def test_forever_loop_survives_a_failed_poll_without_swallowing_interrupt(tmp_path, monkeypatch, inbox):
    cfg, st_file, comments, sent = inbox
    calls = []

    def poll(*a):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transport failed")
        raise KeyboardInterrupt()

    monkeypatch.setattr(daemon, "run_daemon_once", poll)
    monkeypatch.setattr(daemon.time, "sleep", lambda _: None)
    with pytest.raises(KeyboardInterrupt):
        daemon.run_daemon_forever(tmp_path, cfg, Policy(), st_file)
    assert len(calls) == 2
