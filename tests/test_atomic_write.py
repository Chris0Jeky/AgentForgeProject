from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

from agentforge.core.utils import atomic_write_text


def test_concurrent_atomic_writes_use_distinct_temporary_files(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    barrier = Barrier(2, timeout=5)
    original = Path.replace
    sources = []
    rename_lock = Lock()

    def replace_together(source, target):
        if target == path:
            sources.append(source)
            barrier.wait()
        # Windows may reject simultaneous replacement of the same destination.
        with rename_lock:
            return original(source, target)

    monkeypatch.setattr(Path, "replace", replace_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writes = [pool.submit(atomic_write_text, path, value) for value in ("first", "second")]
        for write in writes:
            write.result()
    assert len(set(sources)) == 2
    assert path.read_text(encoding="utf-8") in ("first", "second")
    assert list(tmp_path.iterdir()) == [path]
