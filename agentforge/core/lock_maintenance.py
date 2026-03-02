from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .locks import list_locks, renew_lock, release_lock, LockInfo
from .github import gh_json, GhMissing
from .utils import which
from .state import load_state, save_state, state_lock


@dataclass(frozen=True)
class StickyLockAction:
    group: str
    action: str  # renewed | released | skipped | error
    reason: str = ""
    pr_number: Optional[int] = None


def _now() -> int:
    return int(time.time())


def _pr_status(pr_number: int, *, cwd: Optional[Path] = None) -> Dict[str, Any]:
    """Return a minimal PR status dict using gh.

    We intentionally tolerate schema drift across gh versions by looking at multiple keys.
    """
    j = gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,state,isMerged,mergedAt,closedAt,url",
        ],
        cwd=cwd,
    ) or {}
    state = str(j.get("state") or "").upper()
    is_merged = bool(j.get("isMerged")) if "isMerged" in j else bool(j.get("mergedAt"))
    merged_at = j.get("mergedAt")
    closed_at = j.get("closedAt")
    return {
        "number": int(j.get("number") or pr_number),
        "state": state,
        "is_merged": is_merged,
        "merged_at": merged_at,
        "closed_at": closed_at,
        "url": j.get("url"),
    }


def maintain_sticky_locks(
    root: Path,
    cfg,
    *,
    dry_run: bool = False,
    include_non_sticky: bool = False,
) -> List[StickyLockAction]:
    """Renew sticky locks, and optionally auto-release when their PR is merged/closed.

    Behavior:
    - For sticky locks:
      - If lock.pr_number is set and gh is available: query PR state.
        - If merged (or closed): release the lock.
        - Else: renew the lock.
      - If pr_number isn't set: renew the lock.
    - If include_non_sticky: we also renew all locks that have ttl_sec set (rarely useful).

    This is **best-effort** maintenance. Failures return as actions with action="error".
    """
    actions: List[StickyLockAction] = []
    locks = list_locks(root=root, cfg=cfg)

    gh_ok = which("gh") is not None and bool(getattr(cfg, "repo", None))
    for li in locks:
        if not include_non_sticky and not li.sticky:
            continue

        try:
            ttl = int(li.ttl_sec or getattr(cfg, "sticky_lock_default_ttl_sec", 6 * 60 * 60) or 6 * 60 * 60)

            if li.sticky and li.pr_number and gh_ok and getattr(cfg, "sticky_lock_auto_release", True):
                st = _pr_status(li.pr_number, cwd=root)
                state = str(st.get("state") or "").upper()
                is_merged = bool(st.get("is_merged"))
                if is_merged or state in ["MERGED"]:
                    if not dry_run:
                        release_lock(root=root, cfg=cfg, group=li.group, force=True)
                    actions.append(StickyLockAction(group=li.group, action="released", reason="pr merged", pr_number=li.pr_number))
                    continue
                if state in ["CLOSED"] and not is_merged:
                    if not dry_run:
                        release_lock(root=root, cfg=cfg, group=li.group, force=True)
                    actions.append(StickyLockAction(group=li.group, action="released", reason="pr closed", pr_number=li.pr_number))
                    continue

            # Otherwise, renew
            if not dry_run:
                renew_lock(root=root, cfg=cfg, group=li.group, ttl_sec=ttl, force=True)
            actions.append(StickyLockAction(group=li.group, action="renewed", reason="keepalive", pr_number=li.pr_number))
        except GhMissing as e:
            actions.append(StickyLockAction(group=li.group, action="error", reason=str(e), pr_number=li.pr_number))
        except Exception as e:
            actions.append(StickyLockAction(group=li.group, action="error", reason=str(e), pr_number=li.pr_number))

    return actions


def maybe_maintain_sticky_locks(
    root: Path,
    cfg,
    st_file: Path,
    *,
    dry_run: bool = False,
) -> Optional[List[StickyLockAction]]:
    """Run sticky lock maintenance at most every cfg.lock_renew_interval_sec seconds.

    The timestamp is stored in state.json under key: lock_maint_ts.
    """
    interval = int(getattr(cfg, "lock_renew_interval_sec", 120) or 120)
    now = _now()
    with state_lock(st_file):
        st = load_state(st_file)
        last = int(st.get("lock_maint_ts") or 0)
        if last and (now - last) < interval:
            return None
        st["lock_maint_ts"] = now
        save_state(st_file, st)

    return maintain_sticky_locks(root, cfg, dry_run=dry_run)
