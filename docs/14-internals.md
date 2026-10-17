# Internals (for contributors)

## State model

Repo-local state lives in:
- `.agentforge/state/state.json`

It tracks:
- allocated ports
- workspaces (agent/task -> path/branch)
- PR last processed comment ids

State writers use an OS-owned lock on `state.lock` next to `state.json` and atomic
state replacement. The OS releases ownership when a process exits or is killed.
The lock file stays on disk; do not delete it while processes may be using it.

## Workspace invariants
- workspaces are created under `.worktrees/`
- branches use `af/<agent>/<task>`
- removal refuses dirty worktrees and preserves their state and port on failure

Spawn reserves a port and saves a `spawning` record before creating a branch or
worktree. It marks the record `active` only after metadata and env setup succeed.
Removal saves `removing` intent and frees the record/port only after Git succeeds.
`agentforge list` and `agentforge status` show pending records; automation uses only
active workspaces. Retry the same `spawn` or `rm` command after interruption, or use
`rm` to abandon a pending spawn. Retry checks Git's path/branch metadata and keeps
the reservation if ownership is ambiguous. Branch deletion remains opt-in via
`rm --delete-branch`, and that intent survives an interrupted removal.

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
