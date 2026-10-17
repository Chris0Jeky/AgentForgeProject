from __future__ import annotations

import json
import errno
import os
import time
from contextlib import contextmanager
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
    """Process-owned lock; the OS releases ownership even after a crash."""
    lock = state_file.with_suffix(".lock")
    ensure_dir(lock.parent)
    if os.name == "nt":
        import msvcrt
    else:
        import fcntl
    start = time.monotonic()
    # Never unlink this file: waiters must all lock the same inode.
    with lock.open("a+b") as f:
        while True:
            try:
                if os.name == "nt":
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() - start >= timeout_sec:
                    raise TimeoutError(f"Timed out waiting for state lock: {lock}") from e
                time.sleep(0.1)
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
