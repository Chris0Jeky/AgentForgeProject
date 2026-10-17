import multiprocessing
import time
from pathlib import Path

import pytest

from agentforge.core.state import load_state, save_state, state_lock


def _hold_state_lock(path, ready):
    with state_lock(Path(path)):
        ready.set()
        time.sleep(30)


def test_state_lock_recovers_after_owner_death_without_stealing_live_lock(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, {"sentinel": "preserved"})
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    owner = ctx.Process(target=_hold_state_lock, args=(str(path), ready))
    owner.start()
    try:
        assert ready.wait(10)
        with pytest.raises(TimeoutError):
            with state_lock(path, timeout_sec=0.2):
                pytest.fail("stole a live owner's lock")
        owner.terminate()
        owner.join(10)
        assert not owner.is_alive()
        with state_lock(path, timeout_sec=1):
            assert load_state(path) == {"sentinel": "preserved"}
            save_state(path, {"recovered": True})
        with state_lock(path, timeout_sec=1):
            assert load_state(path) == {"recovered": True}
    finally:
        if owner.is_alive():
            owner.terminate()
        owner.join(10)
