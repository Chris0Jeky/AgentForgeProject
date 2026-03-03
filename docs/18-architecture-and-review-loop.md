# Architecture and Review Loop

This document explains AgentForge as a system, not just as a list of commands.
It focuses on how the pieces work together during real multi-agent PR cycles, and what to extend next.

## 1) System model

AgentForge is a local-first orchestration layer with two planes:

- Control plane:
  - CLI (`agentforge/cli.py`)
  - daemon/webhook handlers
  - workflow engine (`core/workflow.py`)
  - bootstrap scheduler (`core/bootstrap.py`)
  - policy/guardrails (`core/policy.py`, `core/diffscan.py`, `core/locks.py`)
  - run event logging (`core/runs.py`)

- Data plane:
  - git worktrees (`.worktrees/<agent>-<task>/`)
  - per-workspace branches (`af/<agent>/<task>`)
  - local state (`.agentforge/state/`)
  - local logs (`.agentforge/logs/`)
  - optional MCP gateway processes and state

Key invariant:

- `1 task = 1 worktree = 1 branch = 1 directory`

This invariant is the main collision-avoidance mechanism.

## 2) Workflow lifecycle

A typical issue flow:

1. Intake:
  - `bootstrap` reads queue issues and builds a plan (agent, task, lock group, workflow).
2. Isolation:
  - workspace is created from base ref with a dedicated branch.
3. Locking:
  - lock group acquired before code changes.
4. Execution:
  - provider role runs (`implement`, `fix`, `review`, `qa`).
5. Gates:
  - diff guardrails + harness checks.
6. Publish:
  - commit/push and optional PR creation.
7. Iteration:
  - daemon/webhook reacts to strict PR commands.
8. Completion:
  - lock released (or sticky lock maintained until PR closes/merges).

## 3) Concurrency and safety

Concurrency uses layers:

- Filesystem and branch isolation:
  - worktrees prevent shared untracked artifacts and branch context leaks.
- Subsystem locks:
  - lock groups serialize high-conflict areas (for example `frontend`, `backend`, `docs`).
- Policy and diff tripwires:
  - deny/protect glob patterns and suspicious diff signatures reduce unsafe automation.
- Comment command grammar:
  - daemon only accepts strict `/agentforge ...` commands from allowlisted users.

Result:

- high local parallelism with bounded collision risk on one host.

## 4) Review loop: current and target

Current implementation supports:

- human-triggered PR commands (`status`, `review`, `qa`, `fix`)
- repeated fix cycles driven by comments

To reach full autonomous review iteration, implement workflow-level states:

- `pr_open`
- `awaiting_review`
- `needs_fix`
- `retesting`
- `done` / `blocked`

And add workflow steps for:

- request reviewer
- wait for new review events
- apply fixes from review context
- re-request review with max-iteration caps

## 5) v5 operational upgrades

v5 improves operational reliability and contributor ergonomics:

- CI now executes `pytest -q` instead of `unittest` only.
  - this ensures pytest-style tests are actually executed in CI.
- `pyproject.toml` adds `dev` extras with pytest.
- `Makefile` test target now uses pytest.
- root `AGENTS.md` provides repo-specific agent guardrails and working agreements.
- UI/MCP docs clarify action auth behavior (`Authorization: Bearer <token>`).

These changes strengthen quality feedback loops without altering runtime orchestration semantics.

## 6) Architecture ideas that transcend v5

High-leverage next steps:

1. State machine persistence:
  - move from ad-hoc run status to explicit PR/task state transitions.
2. Scheduler:
  - periodic capacity-aware dispatcher that balances queue intake and review-fix loops.
3. Review adapters:
  - unified interface for GitHub review requests (CLI or MCP).
4. Context packs:
  - persist issue + diff + failing checks + review comments for deterministic retries.
5. Failure triage:
  - classify harness failures (lint, unit, integration, env) before choosing next action.
6. Multi-host scaling:
  - distributed lock backend and worker heartbeats when leaving single-host mode.

## 7) Testing strategy

Use three layers:

- Unit tests:
  - lock behavior, diff scanning, parser and config logic.
- Integration tests:
  - local temp repos with worktree + branch + push flow.
- End-to-end tests:
  - controlled GitHub repo for PR/comment/review loop verification.

Keep CI fast and deterministic; isolate network-dependent tests behind explicit flags.
