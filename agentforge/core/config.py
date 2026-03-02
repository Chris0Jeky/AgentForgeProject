from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None

from .utils import out


@dataclass(frozen=True)
class RepoConfig:
    # Repo identity (optional but used for gh integration)
    repo: Optional[str] = None  # "owner/name"

    # Git defaults
    default_remote: str = "origin"
    default_base_branch: str = "main"
    default_base_ref: str = "origin/main"

    # Worktree layout
    worktrees_dir: str = ".worktrees"

    # AgentForge state dirs (inside repo)
    af_dir: str = ".agentforge"
    state_dir: str = ".agentforge/state"
    logs_dir: str = ".agentforge/logs"
    cache_dir: str = ".agentforge/cache"

    # Port pool (for optional stack)
    port_start: int = 8081
    port_end: int = 8180

    # Docker compose integration (optional)
    compose_file: Optional[str] = None
    compose_profile: Optional[str] = None
    compose_project_prefix: str = "af"

    # Harness commands (project-specific)
    harness_setup: List[str] = None  # type: ignore
    harness_check: List[str] = None  # type: ignore

    # Provider + workflow defaults
    default_provider: str = "codex_cli"
    default_workflow: str = "default"
    auto_lock_strategy: str = "labels_then_keywords"

    # Sticky lock maintenance (optional)
    # If you use sticky locks in workflows, the daemon can renew them and
    # auto-release after PR merge/close.
    lock_renew_interval_sec: int = 120
    sticky_lock_default_ttl_sec: int = 6 * 60 * 60
    sticky_lock_auto_release: bool = True

    # GitHub poll interval
    poll_interval_sec: int = 45

    # Issue queue defaults
    queue_label: str = "agent:queued"
    in_progress_label: str = "agent:in-progress"
    done_label: str = "agent:done"


@dataclass(frozen=True)
class Policy:
    mode: str = "fast"  # fast | safe
    allowed_comment_authors: List[str] = None  # type: ignore
    deny_forks: bool = True

    # Path policy
    forbid_globs: List[str] = None  # type: ignore
    protect_globs: List[str] = None  # type: ignore
    protect_behavior: str = "warn"  # warn | halt

    # Diff size heuristic
    max_changed_lines: int = 4000

    # Automation gates
    require_harness_check: bool = True
    allow_auto_push: bool = True
    allow_auto_commit: bool = True


def find_repo_root(start: Optional[Path] = None) -> Path:
    start = start or Path.cwd()
    # Prefer git, but fall back to walking up
    try:
        root = out(["git", "rev-parse", "--show-toplevel"], cwd=start)
        return Path(root)
    except Exception:
        p = start.resolve()
        for _ in range(50):
            if (p / ".git").exists():
                return p
            if p.parent == p:
                break
            p = p.parent
    raise SystemExit("Not inside a git repository (no .git found and git rev-parse failed).")


def _load_toml(path: Path) -> Dict[str, Any]:
    if tomllib is None:
        raise SystemExit("Python 3.11+ required for tomllib.")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_repo_config(root: Path) -> Tuple[RepoConfig, Policy]:
    cfg_path = root / ".agentforge" / "config.toml"
    pol_path = root / ".agentforge" / "policy.toml"
    if not cfg_path.exists() or not pol_path.exists():
        raise SystemExit("Missing .agentforge/config.toml or .agentforge/policy.toml. Run: agentforge init")

    cfg_data = _load_toml(cfg_path)
    pol_data = _load_toml(pol_path)

    def get(d: Dict[str, Any], key: str, default: Any) -> Any:
        return d[key] if key in d else default

    # Config
    repo = get(cfg_data, "repo", None) or None
    default_remote = get(cfg_data, "default_remote", "origin")
    default_base_branch = get(cfg_data, "default_base_branch", "main")
    default_base_ref = get(cfg_data, "default_base_ref", f"{default_remote}/{default_base_branch}")

    rc = RepoConfig(
        repo=repo,
        default_remote=default_remote,
        default_base_branch=default_base_branch,
        default_base_ref=default_base_ref,
        worktrees_dir=get(cfg_data, "worktrees_dir", ".worktrees"),
        af_dir=".agentforge",
        state_dir=get(cfg_data, "state_dir", ".agentforge/state"),
        logs_dir=get(cfg_data, "logs_dir", ".agentforge/logs"),
        cache_dir=get(cfg_data, "cache_dir", ".agentforge/cache"),
        port_start=int(get(cfg_data, "port_start", 8081)),
        port_end=int(get(cfg_data, "port_end", 8180)),
        compose_file=(get(cfg_data, "compose_file", None) or None),
        compose_profile=(get(cfg_data, "compose_profile", None) or None),
        compose_project_prefix=get(cfg_data, "compose_project_prefix", "af"),
        harness_setup=list(get(cfg_data, "harness_setup", [])),
        harness_check=list(get(cfg_data, "harness_check", [])),
        default_provider=get(cfg_data, "default_provider", "codex_cli"),
        default_workflow=get(cfg_data, "default_workflow", "default"),
        auto_lock_strategy=get(cfg_data, "auto_lock_strategy", "labels_then_keywords"),
        lock_renew_interval_sec=int(get(cfg_data, "lock_renew_interval_sec", 120)),
        sticky_lock_default_ttl_sec=int(get(cfg_data, "sticky_lock_default_ttl_sec", 6 * 60 * 60)),
        sticky_lock_auto_release=bool(get(cfg_data, "sticky_lock_auto_release", True)),
        poll_interval_sec=int(get(cfg_data, "poll_interval_sec", 45)),
        queue_label=get(cfg_data, "queue_label", "agent:queued"),
        in_progress_label=get(cfg_data, "in_progress_label", "agent:in-progress"),
        done_label=get(cfg_data, "done_label", "agent:done"),
    )

    pol = Policy(
        mode=get(pol_data, "mode", "fast"),
        allowed_comment_authors=list(get(pol_data, "allowed_comment_authors", [])),
        deny_forks=bool(get(pol_data, "deny_forks", True)),
        forbid_globs=list(get(pol_data, "forbid_globs", [])),
        protect_globs=list(get(pol_data, "protect_globs", [])),
        protect_behavior=get(pol_data, "protect_behavior", "warn"),
        max_changed_lines=int(get(pol_data, "max_changed_lines", 4000)),
        require_harness_check=bool(get(pol_data, "require_harness_check", True)),
        allow_auto_push=bool(get(pol_data, "allow_auto_push", True)),
        allow_auto_commit=bool(get(pol_data, "allow_auto_commit", True)),
    )

    return rc, pol
