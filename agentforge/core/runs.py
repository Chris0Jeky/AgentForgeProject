from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .utils import ensure_dir, atomic_write_text


@dataclass(frozen=True)
class RunMeta:
    """Metadata for a background run (workflow/bootstrap/etc)."""

    run_id: str
    kind: str  # workflow | bootstrap | other
    title: str
    started_ts: int
    finished_ts: Optional[int] = None
    status: str = "running"  # running | finished | failed
    error: Optional[str] = None
    # relative paths (from repo root) to keep portability
    log_relpath: str = ""
    meta_relpath: str = ""


def _now() -> int:
    return int(time.time())


def runs_dir(root: Path, cfg) -> Path:
    return root / cfg.logs_dir / "runs"


def _run_paths(root: Path, cfg, run_id: str) -> Tuple[Path, Path]:
    d = runs_dir(root, cfg)
    ensure_dir(d)
    log_path = d / f"{run_id}.jsonl"
    meta_path = d / f"{run_id}.meta.json"
    return log_path, meta_path


def create_run(root: Path, cfg, *, kind: str, title: str, run_id: str) -> RunMeta:
    log_path, meta_path = _run_paths(root, cfg, run_id)
    meta = RunMeta(
        run_id=run_id,
        kind=kind,
        title=title,
        started_ts=_now(),
        finished_ts=None,
        status="running",
        error=None,
        log_relpath=str(log_path.relative_to(root)),
        meta_relpath=str(meta_path.relative_to(root)),
    )
    atomic_write_text(meta_path, json.dumps(meta.__dict__, indent=2))
    # touch log file
    if not log_path.exists():
        atomic_write_text(log_path, "")
    return meta


def read_run_meta(root: Path, cfg, run_id: str) -> Optional[Dict[str, Any]]:
    _, meta_path = _run_paths(root, cfg, run_id)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def update_run_meta(root: Path, cfg, run_id: str, *, patch: Dict[str, Any]) -> None:
    cur = read_run_meta(root, cfg, run_id) or {}
    cur.update(patch or {})
    _, meta_path = _run_paths(root, cfg, run_id)
    atomic_write_text(meta_path, json.dumps(cur, indent=2))


def append_event(root: Path, cfg, run_id: str, event: Dict[str, Any]) -> None:
    log_path, _ = _run_paths(root, cfg, run_id)
    event = dict(event or {})
    if "ts" not in event:
        event["ts"] = _now()
    line = json.dumps(event, ensure_ascii=False)
    # Append (not atomic) is fine for JSONL; only one writer thread per run.
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def list_runs(root: Path, cfg, *, limit: int = 50) -> List[Dict[str, Any]]:
    d = runs_dir(root, cfg)
    if not d.exists():
        return []
    metas: List[Dict[str, Any]] = []
    for p in d.glob("*.meta.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            metas.append(j)
        except Exception:
            continue
    metas.sort(key=lambda x: int(x.get("started_ts") or 0), reverse=True)
    return metas[:limit]
