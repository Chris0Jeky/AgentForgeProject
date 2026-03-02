from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None

from .guardrails import sanitize_id
from .utils import ensure_dir, atomic_write_text


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
    ttl_sec: int = 0

    # Sticky locks are intended to live beyond a single workflow run.
    # They can be renewed by the daemon, and auto-released when PR merges.
    sticky: bool = False
    pr_number: Optional[int] = None
    branch: Optional[str] = None
    last_renew_ts: int = 0

    # Free-form extra metadata (non-security-critical)
    meta: Optional[Dict[str, Any]] = None


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
    safe = sanitize_id(group)
    return _lock_dir(root, cfg) / f"{safe}.lock.json"


def _read_lock(path: Path) -> Optional[LockInfo]:
    if not path.exists():
        return None
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
        return LockInfo(
            group=str(j.get("group") or ""),
            agent=str(j.get("agent") or ""),
            task=str(j.get("task") or ""),
            hostname=str(j.get("hostname") or ""),
            pid=int(j.get("pid") or 0),
            created_ts=int(j.get("created_ts") or 0),
            expires_ts=int(j.get("expires_ts") or 0),
            ttl_sec=int(j.get("ttl_sec") or j.get("ttl") or 0),
            sticky=bool(j.get("sticky") or False),
            pr_number=int(j["pr_number"]) if j.get("pr_number") is not None else None,
            branch=str(j.get("branch")) if j.get("branch") is not None else None,
            last_renew_ts=int(j.get("last_renew_ts") or 0),
            meta=dict(j.get("meta") or {}) if isinstance(j.get("meta"), dict) else None,
        )
    except Exception:
        return None


def _write_lock_create_exclusive(path: Path, info: LockInfo) -> None:
    ensure_dir(path.parent)
    raw = json.dumps(info.__dict__, indent=2)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(raw)


def _write_lock_replace(path: Path, info: LockInfo) -> None:
    ensure_dir(path.parent)
    raw = json.dumps(info.__dict__, indent=2)
    atomic_write_text(path, raw)


def is_expired(info: LockInfo) -> bool:
    if not info.expires_ts:
        return False
    return _now() > int(info.expires_ts)


def acquire_lock(
    *,
    root: Path,
    cfg,
    group: str,
    agent: str,
    task: str,
    ttl_sec: int = 6 * 60 * 60,
    force: bool = False,
    sticky: bool = False,
    branch: Optional[str] = None,
    pr_number: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> LockInfo:
    """Acquire an exclusive lock for a subsystem.

    Notes:
    - Locks are local to a repo checkout (not distributed).
    - If an existing lock is expired, it may be replaced without --force.
    - If the lock is already held by the same agent/task, it is treated as a renewal.
    """
    group = group.strip()
    if not group:
        raise LockError("group is required")
    path = _lock_path(root, cfg, group)

    now = _now()
    ttl_sec = int(ttl_sec or 0)
    if ttl_sec <= 0:
        ttl_sec = 6 * 60 * 60

    info_new = LockInfo(
        group=group,
        agent=agent,
        task=task,
        hostname=socket.gethostname(),
        pid=os.getpid(),
        created_ts=now,
        expires_ts=now + ttl_sec,
        ttl_sec=ttl_sec,
        sticky=bool(sticky),
        pr_number=int(pr_number) if pr_number is not None else None,
        branch=branch,
        last_renew_ts=now,
        meta=meta,
    )

    # Fast path: create exclusively
    try:
        _write_lock_create_exclusive(path, info_new)
        return info_new
    except FileExistsError:
        pass

    # Existing: read and decide
    holder = _read_lock(path)
    if holder is None:
        # Corrupt file -> allow replace if force
        if not force:
            raise LockError(f"Lock file exists but could not be parsed: {path}. Use --force to replace.")
        _write_lock_replace(path, info_new)
        return info_new

    # Renewal by same owner
    if holder.agent == agent and holder.task == task and not is_expired(holder) and not force:
        renewed = replace(holder, expires_ts=now + ttl_sec, ttl_sec=ttl_sec, last_renew_ts=now)
        _write_lock_replace(path, renewed)
        return renewed

    if not is_expired(holder) and not force:
        raise LockTakenError(group, holder)

    # Replace stale lock (expired) or force steal
    _write_lock_replace(path, info_new)
    return info_new


def update_lock(
    *,
    root: Path,
    cfg,
    group: str,
    agent: Optional[str] = None,
    task: Optional[str] = None,
    force: bool = False,
    patch: Dict[str, Any],
) -> LockInfo:
    """Update fields of an existing lock, optionally verifying ownership."""
    path = _lock_path(root, cfg, group)
    holder = _read_lock(path)
    if holder is None:
        raise LockError(f"Lock '{group}' not found")
    if not force:
        if agent and holder.agent != agent:
            raise LockError(f"Lock '{group}' owned by {holder.agent}:{holder.task}, not {agent}:{task or ''}")
        if task and holder.task != task:
            raise LockError(f"Lock '{group}' owned by {holder.agent}:{holder.task}, not {agent or ''}:{task}")
    # Build a new LockInfo using dataclass replace where possible.
    upd = dict(patch or {})
    # Merge meta dict if provided
    meta = holder.meta
    if "meta" in upd and isinstance(upd["meta"], dict):
        meta = dict(meta or {})
        meta.update(upd["meta"])
        upd["meta"] = meta

    # Normalize certain fields
    if "pr_number" in upd and upd["pr_number"] is not None:
        try:
            upd["pr_number"] = int(upd["pr_number"])
        except Exception:
            upd["pr_number"] = None
    if "ttl_sec" in upd and upd["ttl_sec"] is not None:
        upd["ttl_sec"] = int(upd["ttl_sec"])

    new = replace(holder, **upd)
    _write_lock_replace(path, new)
    return new


def renew_lock(
    *,
    root: Path,
    cfg,
    group: str,
    ttl_sec: Optional[int] = None,
    agent: Optional[str] = None,
    task: Optional[str] = None,
    force: bool = False,
) -> LockInfo:
    """Extend the lock expiry.

    If ttl_sec is None, keep existing ttl_sec (or 6h fallback).
    """
    now = _now()
    holder = _read_lock(_lock_path(root, cfg, group))
    if holder is None:
        raise LockError(f"Lock '{group}' not found")
    ttl = int(ttl_sec if ttl_sec is not None else (holder.ttl_sec or 6 * 60 * 60))
    return update_lock(
        root=root,
        cfg=cfg,
        group=group,
        agent=agent,
        task=task,
        force=force,
        patch={
            "ttl_sec": ttl,
            "expires_ts": now + ttl,
            "last_renew_ts": now,
        },
    )


def mark_lock_sticky(
    *,
    root: Path,
    cfg,
    group: str,
    agent: Optional[str] = None,
    task: Optional[str] = None,
    sticky: bool = True,
    pr_number: Optional[int] = None,
    branch: Optional[str] = None,
    force: bool = False,
) -> LockInfo:
    patch: Dict[str, Any] = {"sticky": bool(sticky)}
    if pr_number is not None:
        patch["pr_number"] = int(pr_number)
    if branch is not None:
        patch["branch"] = branch
    return update_lock(root=root, cfg=cfg, group=group, agent=agent, task=task, force=force, patch=patch)


def release_lock(*, root: Path, cfg, group: str, agent: Optional[str]=None, task: Optional[str]=None, force: bool=False) -> None:
    group = group.strip()
    if not group:
        raise LockError("group is required")
    path = _lock_path(root, cfg, group)
    holder = _read_lock(path)
    if holder is None:
        return
    if not force:
        # Mirror acquire semantics: mismatched owner raises LockTakenError for ergonomics.
        if agent and holder.agent != agent:
            raise LockTakenError(group, holder)
        if task and holder.task != task:
            raise LockTakenError(group, holder)
    try:
        path.unlink()
    except FileNotFoundError:
        return
def list_locks(*, root: Path, cfg) -> List[LockInfo]:
    d = _lock_dir(root, cfg)
    if not d.exists():
        return []
    out_locks: List[LockInfo] = []
    for p in d.glob("*.lock.json"):
        li = _read_lock(p)
        if li:
            out_locks.append(li)
    # newest first
    out_locks.sort(key=lambda x: x.created_ts, reverse=True)
    return out_locks


def load_lock_groups(root: Path) -> LockGroups:
    """Load .agentforge/locks.toml."""
    af = root / ".agentforge"
    p = af / "locks.toml"
    if not p.exists():
        return LockGroups(groups={})

    if tomllib is None:
        raise SystemExit("Python 3.11+ required for tomllib")

    j = tomllib.loads(p.read_text(encoding="utf-8")) or {}
    groups_raw = j.get("groups") or {}
    groups: Dict[str, LockGroupSpec] = {}
    if isinstance(groups_raw, dict):
        for name, spec in groups_raw.items():
            if not isinstance(spec, dict):
                continue
            groups[str(name)] = LockGroupSpec(
                name=str(name),
                globs=list(spec.get("globs") or []),
                labels=list(spec.get("labels") or []),
                keywords=list(spec.get("keywords") or []),
                workflow=str(spec.get("workflow")) if spec.get("workflow") not in [None, ""] else None,
                priority=int(spec.get("priority") or 0),
                default=bool(spec.get("default") or False),
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
