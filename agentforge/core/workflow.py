from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None

from .config import RepoConfig, Policy
from .state import state_paths
from .workspace import list_workspaces, Workspace
from .harness import run_harness_step
from .runner import run_agent_role
from .pr import create_pr
from .github import gh_json, post_pr_comment
from .locks import acquire_lock, release_lock, LockTakenError, mark_lock_sticky
from .utils import ensure_dir


class WorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkflowStepResult:
    step_index: int
    step_type: str
    ok: bool
    message: str = ""


@dataclass(frozen=True)
class WorkflowRunSummary:
    workflow: str
    agent: str
    task: str
    started_ts: int
    finished_ts: int
    results: List[WorkflowStepResult]
    pr_url: Optional[str] = None


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _fmt(s: str, ctx: Dict[str, Any]) -> str:
    try:
        return s.format_map(_SafeDict(ctx))
    except Exception:
        return s


def _eval_bool(v: Any, ctx: Dict[str, Any], *, default: bool = True) -> bool:
    """Evaluate booleans that may be literal bools or template strings.

    Rules:
    - bool -> itself
    - None -> default
    - str -> formatted with ctx, then interpreted via common truthy/falsey strings
    """
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return bool(v)
    s = _fmt(str(v), ctx).strip().lower()
    # If templates remain unresolved, fall back to default (avoid surprises).
    if "{" in s and "}" in s:
        return default
    if s in ["", "0", "false", "no", "off", "n"]:
        return False
    if s in ["1", "true", "yes", "on", "y"]:
        return True
    # Any other string -> default to truthy
    return True


def _load_toml(path: Path) -> Dict[str, Any]:
    if tomllib is None:
        raise SystemExit("Python 3.11+ required for tomllib.")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_workflows(root: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Load `.agentforge/workflows.toml`.

    Schema (v0.3):
      [workflow.<name>]
      steps = [
        {type="lock", action="acquire", group="backend", sticky=true},
        {type="agent", role="implement", provider="codex_cli", prompt="..."},
        {type="pr", action="create", title="...", draft=true},
        ...
      ]
    """
    path = root / ".agentforge" / "workflows.toml"
    if not path.exists():
        raise SystemExit("Missing .agentforge/workflows.toml. Run `agentforge init` (or create the file).")
    data = _load_toml(path)
    wf = data.get("workflow") or {}
    workflows: Dict[str, List[Dict[str, Any]]] = {}
    for name, spec in wf.items():
        steps = list((spec or {}).get("steps") or [])
        workflows[str(name)] = [dict(s) for s in steps]
    return workflows


def _find_ws(state_file: Path, agent: str, task: str) -> Workspace:
    for ws in list_workspaces(state_file):
        if ws.agent == agent and ws.task == task:
            return ws
    raise SystemExit(f"Workspace not found: {agent}:{task}. Use `agentforge spawn` first.")


def _read_prompt(step: Dict[str, Any], root: Path, ws_path: Path, ctx: Dict[str, Any]) -> str:
    if "prompt_file" in step and step["prompt_file"]:
        p = Path(str(step["prompt_file"]))
        # relative paths are relative to repo root by default
        if not p.is_absolute():
            p = root / p
        txt = p.read_text(encoding="utf-8")
        return _fmt(txt, ctx)
    if "prompt" in step and step["prompt"]:
        return _fmt(str(step["prompt"]), ctx)
    return ""


def _get_pr_number(ws_path: Path) -> Optional[int]:
    try:
        j = gh_json(["pr", "view", "--json", "number"], cwd=ws_path) or {}
        return int(j.get("number"))
    except Exception:
        return None


def run_workflow(
    *,
    root: Path,
    cfg: RepoConfig,
    pol: Policy,
    agent: str,
    task: str,
    workflow: str,
    provider_default: Optional[str] = None,
    extra_ctx: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    log_json: bool = True,
    event_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> WorkflowRunSummary:
    """Run a named workflow for an existing workspace.

    event_cb is invoked with JSON-serializable dicts for:
    - workflow_start/workflow_end
    - step_start/step_end
    """
    workflows = load_workflows(root)
    if workflow not in workflows:
        raise SystemExit(f"Workflow not found: {workflow}. Available: {', '.join(sorted(workflows.keys()))}")
    steps = workflows[workflow]

    state_file, logs_dir = state_paths(root, cfg)
    ws = _find_ws(state_file, agent, task)
    ws_path = Path(ws.path)

    provider_default = provider_default or cfg.default_provider

    started = int(time.time())
    results: List[WorkflowStepResult] = []
    pr_url: Optional[str] = None

    # Execution context for templates in steps
    ctx: Dict[str, Any] = {
        "agent": ws.agent,
        "task": ws.task,
        "branch": ws.branch,
        "base_ref": cfg.default_base_ref,
    }
    if extra_ctx:
        ctx.update(extra_ctx)

    def emit(ev: Dict[str, Any]) -> None:
        if not event_cb:
            return
        try:
            event_cb(ev)
        except Exception:
            # Never let logging break the workflow.
            return

    def record(i: int, t: str, ok: bool, msg: str = "", **extra: Any) -> None:
        results.append(WorkflowStepResult(step_index=i, step_type=t, ok=ok, message=msg))
        emit({"type": "step_end", "step_index": i, "step_type": t, "ok": ok, "message": msg, **(extra or {})})

    emit(
        {
            "type": "workflow_start",
            "workflow": workflow,
            "agent": ws.agent,
            "task": ws.task,
            "branch": ws.branch,
            "started_ts": started,
        }
    )

    # Locks acquired during run to ensure release on failure if desired
    held_locks: List[str] = []
    held_sticky: List[str] = []

    for i, step in enumerate(steps):
        stype = str(step.get("type") or "").strip().lower()
        if not stype:
            record(i, "unknown", False, "Missing step.type")
            raise WorkflowError(f"Step {i} missing 'type'")

        enabled = _eval_bool(step.get("enabled", True), ctx, default=True)
        if not enabled:
            record(i, stype, True, "skipped")
            continue

        if dry_run:
            record(i, stype, True, f"DRY RUN: {step}")
            continue

        emit({"type": "step_start", "step_index": i, "step_type": stype, "step": step})

        try:
            if stype == "lock":
                action = str(step.get("action") or "acquire").lower()
                group = _fmt(str(step.get("group") or "").strip(), ctx)
                ttl = int(step.get("ttl_sec") or 6 * 60 * 60)
                force = bool(step.get("force") or False)
                sticky = _eval_bool(step.get("sticky", False), ctx, default=False)
                if not group:
                    raise WorkflowError("lock step requires group")
                if action == "acquire":
                    acquire_lock(
                        root=root,
                        cfg=cfg,
                        group=group,
                        agent=ws.agent,
                        task=ws.task,
                        ttl_sec=ttl,
                        force=force,
                        sticky=sticky,
                        branch=ws.branch if sticky else None,
                    )
                    held_locks.append(group)
                    if sticky:
                        held_sticky.append(group)
                    record(i, stype, True, f"acquired {group}", sticky=sticky)
                elif action == "release":
                    release_lock(root=root, cfg=cfg, group=group, agent=ws.agent, task=ws.task, force=force)
                    if group in held_locks:
                        held_locks.remove(group)
                    if group in held_sticky:
                        held_sticky.remove(group)
                    record(i, stype, True, f"released {group}")
                else:
                    raise WorkflowError(f"Unknown lock action: {action}")

            elif stype == "harness":
                name = str(step.get("name") or step.get("step") or "check")
                ok = run_harness_step(root=root, cfg=cfg, ws=ws, step=name)
                if not ok:
                    raise WorkflowError(f"Harness step failed: {name}")
                record(i, stype, True, f"harness {name} ok")

            elif stype == "agent":
                role = str(step.get("role") or "implement")
                provider = str(step.get("provider") or provider_default)
                prompt = _read_prompt(step, root, ws_path, ctx)
                auto_commit = bool(step.get("auto_commit") if "auto_commit" in step else pol.allow_auto_commit)
                auto_push = bool(step.get("auto_push") if "auto_push" in step else pol.allow_auto_push)
                run_agent_role(
                    root,
                    cfg,
                    pol,
                    ws,
                    provider=provider,
                    role=role,
                    prompt=prompt,
                    auto_commit=auto_commit,
                    auto_push=auto_push,
                )
                record(i, stype, True, f"agent role={role} provider={provider}")

            elif stype == "pr":
                action = str(step.get("action") or "create").lower()
                if action != "create":
                    raise WorkflowError("Only pr action=create supported in v0.3")
                title = _fmt(str(step.get("title") or f"[{ws.agent}] {ws.task}"), ctx)
                body = _fmt(str(step.get("body") or "Automated by AgentForge."), ctx)
                draft_raw = step.get("draft") if "draft" in step else True
                draft = _eval_bool(draft_raw, ctx, default=True)
                base_branch = str(step.get("base") or cfg.default_base_branch)
                created = create_pr(ws_path=ws_path, title=title, body=body, base=base_branch, head=ws.branch, draft=draft)
                pr_url = created.url
                ctx["pr_url"] = pr_url
                ctx["pr_number"] = created.number

                # Attach PR metadata to sticky locks (best-effort)
                for g in list(held_sticky):
                    try:
                        mark_lock_sticky(
                            root=root,
                            cfg=cfg,
                            group=g,
                            agent=ws.agent,
                            task=ws.task,
                            sticky=True,
                            pr_number=created.number,
                            branch=ws.branch,
                            force=False,
                        )
                    except Exception:
                        # Don't fail a workflow if the lock disappeared or was stolen.
                        pass

                record(i, stype, True, f"created {pr_url}", pr_number=created.number)

            elif stype == "comment":
                prn = step.get("pr_number")
                # If not provided, infer from current branch.
                pr_number = int(_fmt(str(prn), ctx)) if prn is not None else _get_pr_number(ws_path)
                if not pr_number:
                    raise WorkflowError("Could not determine PR number for comment step")
                body = _fmt(str(step.get("body") or ""), ctx)
                if not body:
                    body = "AgentForge: (empty comment)"
                post_pr_comment(int(pr_number), body)
                record(i, stype, True, f"commented on PR #{pr_number}")

            elif stype == "sleep":
                sec = float(step.get("sec") or 1)
                time.sleep(sec)
                record(i, stype, True, f"slept {sec}s")

            elif stype == "note":
                msg = _fmt(str(step.get("message") or ""), ctx)
                record(i, stype, True, msg)

            elif stype == "mcp_gateway":
                # Optional: ensure an MCP Gateway is running (Docker MCP Toolkit).
                action = str(step.get("action") or "ensure").lower()
                scope = str(step.get("scope") or "workspace").lower()  # workspace | repo
                transport = str(step.get("transport") or "").strip() or None
                if action not in ["ensure", "start", "stop"]:
                    raise WorkflowError(f"Unknown mcp_gateway action: {action}")

                from .mcp import load_mcp_config, ensure_gateway_running, stop_gateway

                mcfg = load_mcp_config(root)
                if action in ["ensure", "start"]:
                    key = None if scope == "repo" else f"{ws.agent}::{ws.task}"
                    gw = ensure_gateway_running(root, cfg, mcfg, key=key, transport=transport)
                    # Expose to downstream steps
                    if gw.get("url"):
                        ctx["mcp_gateway_url"] = gw["url"]
                    if gw.get("auth_token"):
                        ctx["mcp_gateway_auth_token"] = gw["auth_token"]
                    ctx["mcp_profile"] = gw.get("profile") or mcfg.profile
                    record(i, stype, True, f"gateway running ({gw.get('transport')})", url=gw.get("url"))
                else:  # stop
                    key = None if scope == "repo" else f"{ws.agent}::{ws.task}"
                    stop_gateway(root, cfg, key=key)
                    record(i, stype, True, "gateway stopped")

            else:
                raise WorkflowError(f"Unknown step type: {stype}")

        except LockTakenError as e:
            record(i, stype, False, str(e), holder=e.holder.__dict__)
            # Stop workflow; locks remain held (by someone else) anyway.
            break
        except Exception as e:
            record(i, stype, False, str(e))
            # Stop workflow on first failure. (Workflows can model retries explicitly.)
            break

    finished = int(time.time())
    summary = WorkflowRunSummary(
        workflow=workflow,
        agent=ws.agent,
        task=ws.task,
        started_ts=started,
        finished_ts=finished,
        results=results,
        pr_url=pr_url,
    )

    emit({"type": "workflow_end", "workflow": workflow, "agent": ws.agent, "task": ws.task, "finished_ts": finished, "pr_url": pr_url})

    if log_json:
        ensure_dir(logs_dir)
        log_path = Path(logs_dir) / f"{started}-workflow-{ws.agent}-{ws.task}.json"
        log_path.write_text(json.dumps(summary, default=lambda o: o.__dict__, indent=2), encoding="utf-8")

    return summary
