import json
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agentforge.core import mcp
from agentforge.core.config import RepoConfig


def _start_worker(root, key, barrier, results):
    root = Path(root)
    mcp.docker_mcp_available = lambda: True
    mcp._gateway_ready = lambda info: True

    def spawn(cmd, **kwargs):
        with (root / "launches.txt").open("a", encoding="utf-8") as stream:
            stream.write(key + "\n")
        return SimpleNamespace(pid=os.getpid(), poll=lambda: None)

    mcp.subprocess.Popen = spawn
    barrier.wait(timeout=10)
    try:
        mcp.ensure_gateway_running(root, RepoConfig(), mcp.McpConfig(gateway_auto_sync=False), key=key)
        results.put("started")
    except mcp.McpError:
        results.put("unresolved")


@pytest.mark.parametrize("keys", [("a", "b"), ("a", "a")])
def test_cross_process_starts_preserve_all_intents_without_duplicate_launches(tmp_path, keys):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(3)
    results = ctx.Queue()
    workers = [ctx.Process(target=_start_worker, args=(str(tmp_path), key, barrier, results)) for key in keys]
    try:
        for worker in workers:
            worker.start()
        barrier.wait(timeout=10)
        assert len(mcp.list_gateways(tmp_path, RepoConfig())) <= len(set(keys))
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0
        outcomes = [results.get(timeout=2) for _ in workers]
        store = tmp_path / RepoConfig().state_dir / "mcp_gateways.json"
        records = json.loads(store.read_text(encoding="utf-8"))
        assert set(records) == set(keys)
        launches = (tmp_path / "launches.txt").read_text(encoding="utf-8").splitlines()
        assert sorted(launches) == sorted(set(keys))
        assert outcomes.count("started") == len(set(keys))
        assert len({r["port"] for r in records.values()}) == len(set(keys))
        assert len(mcp.list_gateways(tmp_path, RepoConfig())) == len(set(keys))
        assert json.loads(store.read_text(encoding="utf-8")) == records
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=3)
        results.close()


def test_failed_publication_retains_intent_and_prevents_second_launch(tmp_path, monkeypatch):
    cfg = RepoConfig()
    process = SimpleNamespace(pid=123, poll=lambda: None)
    spawn = Mock(return_value=process)
    monkeypatch.setattr(mcp, "docker_mcp_available", lambda: True)
    monkeypatch.setattr(mcp, "_gateway_ready", lambda _: True)
    monkeypatch.setattr(mcp.subprocess, "Popen", spawn)
    save = mcp._save_gateways

    def fail_after_spawn(root, cfg, records):
        if spawn.called:
            raise OSError("publication failed")
        save(root, cfg, records)

    monkeypatch.setattr(mcp, "_save_gateways", fail_after_spawn)
    with pytest.raises(OSError, match="publication failed"):
        mcp.ensure_gateway_running(tmp_path, cfg, mcp.McpConfig(gateway_auto_sync=False), key="a")
    record = json.loads((tmp_path / cfg.state_dir / "mcp_gateways.json").read_text(encoding="utf-8"))["a"]
    assert record["state"] == "launching" and record["operation_id"]
    monkeypatch.setattr(mcp, "_save_gateways", save)
    recovered = mcp.ensure_gateway_running(tmp_path, cfg, mcp.McpConfig(gateway_auto_sync=False), key="a")
    assert recovered["operation_id"] == record["operation_id"]
    assert recovered["pid"] == 123 and recovered["state"] == "running"
    spawn.assert_called_once()


def test_endpoint_requires_fresh_token_attestation(monkeypatch):
    connections = []

    class Connection:
        def __init__(self, *a, **kw):
            connections.append(self)

        def request(self, method, path, headers):
            self.headers = headers

        def getresponse(self):
            return SimpleNamespace(status=200 if self.headers else 401)

        def close(self):
            pass

    monkeypatch.setattr(mcp.http.client, "HTTPConnection", Connection)
    info = {"transport": "sse", "url": "http://127.0.0.1:9360", "auth_token": "nonce"}
    assert mcp._gateway_ready(info)
    assert connections[1].headers == {"Authorization": "Bearer nonce"}
    monkeypatch.setattr(Connection, "getresponse", lambda _: SimpleNamespace(status=200))
    assert not mcp._gateway_ready(info)


def test_lost_spawn_return_preserves_unresolved_intent(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "docker_mcp_available", lambda: True)
    spawn = Mock(side_effect=KeyboardInterrupt())
    monkeypatch.setattr(mcp.subprocess, "Popen", spawn)
    with pytest.raises(KeyboardInterrupt):
        mcp.ensure_gateway_running(tmp_path, RepoConfig(), mcp.McpConfig(gateway_auto_sync=False), key="a")
    with pytest.raises(mcp.McpError, match="ownership.*reconcile"):
        mcp.ensure_gateway_running(tmp_path, RepoConfig(), mcp.McpConfig(gateway_auto_sync=False), key="a")
    assert mcp._load_gateways(tmp_path, RepoConfig())["a"]["state"] == "launching"
    spawn.assert_called_once()
