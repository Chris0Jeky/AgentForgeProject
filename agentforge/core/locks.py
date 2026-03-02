from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None

from .guardrails import sanitize_id
from .utils import ensure_dir


class LockError(RuntimeError):
    pass


class LockTakenError(LockError):
    def __init__(self, group: str, holder: "LockInfo"):
        super().__init__(f"Lock '{group}' is held by {holder.agent}:{holder.task} on {holder.hostname} (pid {holder.pid})")
        self.group = group
        self.holder = holder


@dataclass(frozen=True)
class LockInfo:
    group: str
    agent: str
    task: str
    hostname: str
    pid: int
    created_ts: int
    expires_ts: int


@dataclass(frozen=True)
class LockGroupSpec:
    """Metadata for a lock group.

    This is *not* security-critical; it exists to help automation decide which
    lock group (and workflow) to use for a given task/issue.
    """

    name: str
    globs: List[str]
    labels: List[str]
    keywords: List[str]
    workflow: Optional[str] = None
    priority: int = 0
    default: bool = False


@dataclass(frozen=True)
class LockGroups:
    groups: Dict[str, LockGroupSpec]  # group -> spec

    def get(self, name: str) -> Optional[LockGroupSpec]:
        return self.groups.get(name)

    def default_group(self) -> Optional[LockGroupSpec]:
        # Prefer explicit default=true; else fall back to group named "repo"; else None.
        defaults = [g for g in self.groups.values() if g.default]
        if defaults:
            return sorted(defaults, key=lambda s: (s.priority, s.name), reverse=True)[0]
        if "repo" in self.groups:
            return self.groups["repo"]
        return None

    def sorted(self) -> List[LockGroupSpec]:
        return sorted(self.groups.values(), key=lambda s: (-s.priority, s.name))


def _now() -> int:
    return int(time.time())


def _lock_dir(root: Path, cfg) -> Path:
    return root / cfg.state_dir / "locks"


def _lock_path(root: Path, cfg, group: str) -> Path:
    return _lock_dir(root, cfg) / f"{sanitize_id(group)}.lock.json"


def _read_lock(path: Path) -> Optional[LockInfo]:
    if not path.exists():
        return None
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
        return LockInfo(
            group=j.get("group", ""),
            agent=j.get("agent", ""),
            task=j.get("task", ""),
            hostname=j.get("hostname", ""),
            pid=int(j.get("pid", 0)),
            created_ts=int(j.get("created_ts", 0)),
            expires_ts=int(j.get("expires_ts", 0)),
        )
    except Exception:
        return None


def _write_lock_atomic(path: Path, info: LockInfo) -> None:
    # Atomic lock acquisition via exclusive create
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, json.dumps(info.__dict__, indent=2, sort_keys=True).encode("utf-8"))
    finally:
        os.close(fd)


def is_expired(info: LockInfo) -> bool:
    return info.expires_ts > 0 and _now() > info.expires_ts


def acquire_lock(
    *,
    root: Path,
    cfg,
    group: str,
    agent: str,
    task: str,
    ttl_sec: int = 6 * 60 * 60,
    force: bool = False,
    steal_expired: bool = True,
) -> LockInfo:
    """Acquire an exclusive lock for `group`.

    Implementation notes:
    - Uses a lock file in `.agentforge/state/locks/`.
    - Acquisition is atomic via O_EXCL create.
    - If lock exists:
      - if expired and steal_expired: can steal (without requiring --force)
      - else raises LockTakenError unless force=True (force steals immediately)

    Security note:
    - This is a local coordination primitive, not a security boundary.
    """
    group_id = sanitize_id(group)
    d = _lock_dir(root, cfg)
    ensure_dir(d)
    path = _lock_path(root, cfg, group_id)

    hostname = socket.gethostname()
    pid = os.getpid()
    created = _now()
    expires = created + int(ttl_sec) if ttl_sec > 0 else 0
    info = LockInfo(group=group_id, agent=agent, task=task, hostname=hostname, pid=pid, created_ts=created, expires_ts=expires)

    # Fast path: no file yet
    try:
        _write_lock_atomic(path, info)
        return info
    except FileExistsError:
        holder = _read_lock(path)
        if holder is None:
            # Unknown contents -> force required
            if not force:
                raise LockError(f"Lock '{group_id}' exists but is unreadable; use --force to steal: {path}")
        else:
            if not force:
                if is_expired(holder) and steal_expired:
                    # Allow stealing expired without explicit --force
                    pass
                else:
                    raise LockTakenError(group_id, holder)

        # Steal: move old lock aside, then retry atomic create
        stale = path.with_suffix(f".stale.{_now()}.json")
        try:
            path.replace(stale)
        except Exception:
            # If replace fails, force-remove
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

        _write_lock_atomic(path, info)
        return info


def release_lock(
    *,
    root: Path,
    cfg,
    group: str,
    agent: Optional[str] = None,
    task: Optional[str] = None,
    force: bool = False,
) -> None:
    """Release lock.

    If agent/task provided and force=False, only releases if it matches owner.
    """
    path = _lock_path(root, cfg, group)
    if not path.exists():
        return
    holder = _read_lock(path)
    if holder and not force and agent and task:
        if holder.agent != agent or holder.task != task:
            raise LockTakenError(group, holder)
    path.unlink(missing_ok=True)


def list_locks(*, root: Path, cfg) -> List[LockInfo]:
    d = _lock_dir(root, cfg)
    if not d.exists():
        return []
    locks: List[LockInfo] = []
    for p in d.glob("*.lock.json"):
        info = _read_lock(p)
        if info:
            locks.append(info)
    locks.sort(key=lambda x: x.group)
    return locks


def load_lock_groups(root: Path) -> LockGroups:
    """Load `.agentforge/locks.toml` (metadata) if present; else empty.

    Schema (v0.2; backward compatible with v0.1):
      [groups.<name>]
      globs = ["frontend/**"]
      labels = ["area:frontend", "frontend"]
      keywords = ["ui", "web"]
      workflow = "frontend"
      priority = 50
      default = false

    Only `globs` is required; everything else is optional.
    """
    cfg_path = root / ".agentforge" / "locks.toml"
    if not cfg_path.exists():
        return LockGroups(groups={})
    if tomllib is None:
        raise SystemExit("Python 3.11+ required for tomllib.")

    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    raw_groups = data.get("groups") or {}

    groups: Dict[str, LockGroupSpec] = {}
    for k, v in raw_groups.items():
        spec = v or {}
        name = str(k)
        globs = [str(g) for g in list(spec.get("globs") or [])]
        labels = [str(x) for x in list(spec.get("labels") or [])]
        keywords = [str(x) for x in list(spec.get("keywords") or [])]
        workflow = spec.get("workflow", None) or None
        try:
            priority = int(spec.get("priority", 0))
        except Exception:
            priority = 0
        default = bool(spec.get("default", False))
        groups[name] = LockGroupSpec(
            name=name,
            globs=globs,
            labels=labels,
            keywords=keywords,
            workflow=str(workflow) if workflow else None,
            priority=priority,
            default=default,
        )

    return LockGroups(groups=groups)


def select_lock_group_for_issue(
    groups: LockGroups,
    *,
    issue_labels: Optional[List[str]] = None,
    issue_title: str = "",
    strategy: str = "labels_then_keywords",
) -> Optional[LockGroupSpec]:
    """Pick a lock group spec for an issue.

    Strategies:
    - none
    - labels
    - keywords
    - labels_then_keywords (default)

    Matching rules (case-insensitive):
    - labels: any overlap between issue labels and group.labels
    - keywords: any substring match of group.keywords in issue title

    Selection rules:
    - Prefer label matches over keyword matches.
    - Use group.priority as the main score (higher is preferred).
    - Tie-break by group name.
    """
    strategy = (strategy or "labels_then_keywords").strip().lower()
    if strategy in ["none", "off", "false", "0"]:
        return groups.default_group()

    labels_norm = {str(x).strip().lower() for x in (issue_labels or []) if str(x).strip()}
    title_norm = (issue_title or "").strip().lower()

    def score(spec: LockGroupSpec, *, label_match: bool, match_count: int) -> tuple:
        # Primary: label match beats keyword match.
        # Secondary: priority.
        # Tertiary: number of matches.
        return (1 if label_match else 0, spec.priority, match_count, spec.name)

    candidates: List[tuple[tuple, LockGroupSpec]] = []

    if strategy in ["labels", "labels_then_keywords"]:
        for spec in groups.groups.values():
            if not spec.labels:
                continue
            spec_labels = {s.strip().lower() for s in spec.labels if s.strip()}
            inter = labels_norm.intersection(spec_labels)
            if inter:
                candidates.append((score(spec, label_match=True, match_count=len(inter)), spec))

        if candidates:
            # Pick best (max)
            return sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]

        if strategy == "labels":
            return groups.default_group()

    if strategy in ["keywords", "labels_then_keywords"]:
        kw_candidates: List[tuple[tuple, LockGroupSpec]] = []
        for spec in groups.groups.values():
            if not spec.keywords:
                continue
            kws = [k.strip().lower() for k in spec.keywords if k.strip()]
            hits = [k for k in kws if k in title_norm]
            if hits:
                kw_candidates.append((score(spec, label_match=False, match_count=len(hits)), spec))
        if kw_candidates:
            return sorted(kw_candidates, key=lambda x: x[0], reverse=True)[0][1]

    return groups.default_group()
