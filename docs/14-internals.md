# Internals (for contributors)

## State model

Repo-local state lives in:
- `.agentforge/state/state.json`

It tracks:
- allocated ports
- workspaces (agent/task -> path/branch)
- PR last processed comment ids

State is locked via a lock file next to state.json.

## Workspace invariants
- workspaces are created under `.worktrees/`
- branches use `af/<agent>/<task>`
- workspaces are disposable; remove+recreate is cheap

## Execution model
AgentForge is intentionally synchronous in v0.x:
- deterministic behavior
- easy to reason about logs and side-effects

Parallel execution can be added later with:
- a worker queue
- per-workspace locks
- bounded concurrency

## Provider boundary
Providers are the only integration point with “agents”:
- Codex CLI adapter uses `codex exec`
- Shell adapter can wrap other CLIs
- external plugins can register entry points
