import json
import multiprocessing
from dataclasses import replace
from pathlib import Path

import pytest

from agentforge.core import locks
from agentforge.core.config import RepoConfig


def _lock_operation(root, action, agent, reading, proceed, started, done, results):
    cfg = RepoConfig()
    original = locks._read_lock
    reads = 0

    def paused_read(path):
        nonlocal reads
        holder = original(path)
        reads += 1
        if action != "renew" or reads == 2:
            reading.set()
            if proceed is not None:
                assert proceed.wait(10)
        return holder

    locks._read_lock = paused_read
    started.set()
    try:
        kwargs = dict(root=Path(root), cfg=cfg, group="repo", agent=agent, task="task")
        if action == "acquire":
            locks.acquire_lock(**kwargs)
        elif action == "renew":
            locks.renew_lock(**kwargs)
        else:
            locks.release_lock(**kwargs)
        results.put((agent, "ok"))
    except locks.LockTakenError:
        results.put((agent, "taken"))
    finally:
        done.set()


@pytest.mark.parametrize("action", ["acquire", "renew", "release"])
def test_expired_lock_mutations_are_serialized(tmp_path, action):
    cfg = RepoConfig()
    old = locks.acquire_lock(root=tmp_path, cfg=cfg, group="repo", agent="old", task="task")
    path = locks._lock_path(tmp_path, cfg, "repo")
    path.write_text(json.dumps(replace(old, expires_ts=1).__dict__), encoding="utf-8")
    ctx = multiprocessing.get_context("spawn")
    a_read, b_read, proceed, a_start, b_start, a_done, b_done = [ctx.Event() for _ in range(7)]
    results = ctx.Queue()
    first_agent = "a" if action == "acquire" else "old"
    a = ctx.Process(target=_lock_operation, args=(str(tmp_path), action, first_agent, a_read, proceed, a_start, a_done, results))
    b = ctx.Process(target=_lock_operation, args=(str(tmp_path), "acquire", "b", b_read, None, b_start, b_done, results))
    a.start()
    try:
        assert a_read.wait(10)
        b.start()
        assert b_start.wait(10)
        # On the broken implementation B can finish while A still holds a stale read.
        if b_read.wait(0.5):
            assert b_done.wait(10)
        proceed.set()
        a.join(10)
        b.join(10)
        assert a.exitcode == b.exitcode == 0
        outcomes = dict(results.get(timeout=2) for _ in range(2))
        current = locks.list_locks(root=tmp_path, cfg=cfg)
        if action == "release":
            assert outcomes == {"old": "ok", "b": "ok"}
            assert len(current) == 1 and current[0].agent == "b"
        else:
            assert sorted(outcomes.values()) == ["ok", "taken"]
            assert len(current) == 1
            assert outcomes[current[0].agent] == "ok"
    finally:
        proceed.set()
        for child in (a, b):
            if child.pid is not None:
                if child.is_alive():
                    child.terminate()
                child.join(10)
        results.close()


def test_stale_lease_cannot_mutate_same_owner_successor(tmp_path):
    cfg = RepoConfig()
    kwargs = dict(root=tmp_path, cfg=cfg, group="repo", agent="a", task="task")
    old = locks.acquire_lock(**kwargs)
    successor = locks.acquire_lock(**kwargs, force=True)
    assert old.lease_id != successor.lease_id
    with pytest.raises(locks.LockTakenError):
        locks.renew_lock(**kwargs, lease_id=old.lease_id)
    with pytest.raises(locks.LockTakenError):
        locks.release_lock(**kwargs, lease_id=old.lease_id)
    assert locks.list_locks(root=tmp_path, cfg=cfg) == [successor]
    locks.release_lock(**kwargs, lease_id=successor.lease_id)
    assert locks.list_locks(root=tmp_path, cfg=cfg) == []


@pytest.mark.parametrize("pr_state", [None, "MERGED", "CLOSED"])
def test_sticky_maintenance_cannot_mutate_successor(tmp_path, monkeypatch, pr_state):
    from agentforge.core import lock_maintenance

    cfg = RepoConfig(repo="fake/repo" if pr_state else None)
    kwargs = dict(root=tmp_path, cfg=cfg, group="repo", agent="a", task="task")
    old = locks.acquire_lock(**kwargs, sticky=True, pr_number=1)
    successor = locks.acquire_lock(**kwargs, force=True)
    monkeypatch.setattr(lock_maintenance, "list_locks", lambda **_: [old])
    monkeypatch.setattr(lock_maintenance, "which", lambda _: "fake-gh")
    monkeypatch.setattr(lock_maintenance, "_pr_status", lambda *a, **kw: {"state": pr_state})
    actions = lock_maintenance.maintain_sticky_locks(tmp_path, cfg)
    assert locks.list_locks(root=tmp_path, cfg=cfg) == [successor]
    assert actions[0].action == "error"


def test_workflow_release_cannot_remove_same_owner_successor(tmp_path, monkeypatch):
    from agentforge.core import workflow
    from agentforge.core.config import Policy
    from agentforge.core.workspace import Workspace

    cfg = RepoConfig()
    ws = Workspace("a", "task", str(tmp_path), "af/a/task", 8081)
    monkeypatch.setattr(workflow, "_find_ws", lambda *args: ws)
    monkeypatch.setattr(workflow, "load_workflows", lambda _: {"test": [
        {"type": "lock", "group": "repo"},
        {"type": "harness"},
        {"type": "lock", "group": "repo", "action": "release"},
    ]})
    successors = []

    def takeover(**kwargs):
        successors.append(locks.acquire_lock(root=tmp_path, cfg=cfg, group="repo", agent="a", task="task", force=True))
        return True

    monkeypatch.setattr(workflow, "run_harness_step", takeover)
    summary = workflow.run_workflow(root=tmp_path, cfg=cfg, pol=Policy(), agent="a", task="task", workflow="test", log_json=False)
    assert not summary.results[-1].ok
    assert locks.list_locks(root=tmp_path, cfg=cfg) == successors
