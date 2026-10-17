import json
from unittest.mock import Mock
import os
from types import SimpleNamespace

import pytest

from agentforge.core import mcp
from agentforge.core.config import RepoConfig


def test_reused_or_unprovable_pid_is_never_signalled_or_reused(tmp_path, monkeypatch):
    cfg = RepoConfig()
    path = tmp_path / cfg.state_dir / "mcp_gateways.json"
    path.parent.mkdir(parents=True)
    record = {"pid": 123, "key": "test", "url": "http://127.0.0.1:9360"}
    path.write_text(json.dumps({"test": record}), encoding="utf-8")
    kill = Mock()
    monkeypatch.setattr(mcp.os, "kill", kill)
    monkeypatch.setattr(mcp, "docker_mcp_available", lambda: True)
    with pytest.raises(mcp.McpError, match="ownership.*reconcile"):
        mcp.stop_gateway(tmp_path, cfg, key="test")
    with pytest.raises(mcp.McpError, match="ownership.*reconcile"):
        mcp.ensure_gateway_running(tmp_path, cfg, mcp.McpConfig(), key="test")
    assert json.loads(path.read_text(encoding="utf-8"))["test"] == record
    assert mcp.list_gateways(tmp_path, cfg)[0]["state"] == "unresolved"
    kill.assert_not_called()


@pytest.mark.parametrize("failure", [None, "permissions", "exit_and_reuse"])
def test_stop_uses_retained_handle_and_keeps_unconfirmed_records(tmp_path, monkeypatch, failure):
    cfg = RepoConfig()
    process = SimpleNamespace(pid=123, poll=Mock(return_value=None), wait=Mock(), terminate=Mock())
    kill = Mock()
    monkeypatch.setattr(mcp.os, "kill", kill)
    monkeypatch.setattr(mcp, "docker_mcp_available", lambda: True)
    monkeypatch.setattr(mcp, "_gateway_ready", lambda _: True)
    monkeypatch.setattr(mcp.subprocess, "Popen", lambda *a, **kw: process)
    signal_handle = Mock()
    if os.name != "nt":
        monkeypatch.setattr(mcp.os, "pidfd_open", lambda _: os.open(os.devnull, os.O_RDONLY))
        monkeypatch.setattr(mcp.signal, "pidfd_send_signal", signal_handle)
    info = mcp.ensure_gateway_running(tmp_path, cfg, mcp.McpConfig(gateway_auto_sync=False), key="test")
    assert mcp.ensure_gateway_running(tmp_path, cfg, mcp.McpConfig(), key="test") == info
    terminate = process.terminate if os.name == "nt" else signal_handle
    if failure == "permissions":
        terminate.side_effect = PermissionError("denied")
        with pytest.raises(mcp.McpError, match="stop unconfirmed"):
            mcp.stop_gateway(tmp_path, cfg, key="test")
        assert mcp._load_gateways(tmp_path, cfg)["test"] == info
    else:
        if failure == "exit_and_reuse":
            # The saved numeric PID may now name another process; the retained handle is unchanged.
            terminate.side_effect = ProcessLookupError("original process exited")
            with pytest.raises(mcp.McpError, match="stop unconfirmed"):
                mcp.stop_gateway(tmp_path, cfg, key="test")
        else:
            mcp.stop_gateway(tmp_path, cfg, key="test")
            assert mcp._load_gateways(tmp_path, cfg) == {}
        terminate.assert_called_once()
    kill.assert_not_called()
