from pathlib import Path

from agentforge.core.state import load_state, save_state


def test_load_state_defaults_when_missing(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    assert load_state(state_file) == {"ports": {}, "workspaces": {}, "prs": {}}


def test_save_and_load_state_roundtrip(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    expected = {
        "ports": {"8081": {"agent": "a1", "task": "t1"}},
        "workspaces": {"a1:t1": {"path": "/tmp/ws"}},
        "prs": {"123": {"last_comment_id": 999}},
    }
    save_state(state_file, expected)
    loaded = load_state(state_file)
    assert loaded == expected
