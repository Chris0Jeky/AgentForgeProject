from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

from .utils import ensure_dir, atomic_write_text

def state_paths(root: Path, cfg) -> Tuple[Path, Path]:
    state_dir = root / cfg.state_dir
    logs_dir = root / cfg.logs_dir
    ensure_dir(state_dir)
    ensure_dir(logs_dir)
    return state_dir / "state.json", logs_dir

def load_state(state_file: Path) -> Dict[str, Any]:
    if not state_file.exists():
        return {"ports": {}, "workspaces": {}, "prs": {}}
    return json.loads(state_file.read_text(encoding="utf-8"))

def save_state(state_file: Path, st: Dict[str, Any]) -> None:
    atomic_write_text(state_file, json.dumps(st, indent=2, sort_keys=True))

@contextmanager
def state_lock(state_file: Path, timeout_sec: int = 10) -> Iterator[None]:
    """Cross-platform lock using exclusive create of a lock file.

    Not perfect, but good enough for a single-machine daemon + CLI calls.
    """
    lock = state_file.with_suffix(".lock")
    start = time.time()
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - start > timeout_sec:
                raise TimeoutError(f"Timed out waiting for state lock: {lock}")
            time.sleep(0.1)
    try:
        yield
    finally:
        try:
            lock.unlink(missing_ok=True)  # py3.8+
        except Exception:
            pass
