# Container sandbox runner (design)

This is a recommended upgrade once you are ready for stronger isolation.

## Goal
Run the agent process in a container where:
- only the worktree is writable
- the host filesystem is not visible
- network can be restricted by role

## Approach
1) Build a small runtime image containing:
- your toolchain (dotnet/node/etc)
- the provider CLI (codex, etc) if needed

2) Run with:
- bind mount: /workspace -> worktree path
- user namespace / non-root user
- drop capabilities
- `--network none` for review roles

3) Update AgentForge with a new Provider adapter:
- `docker_runner`
- it wraps a normal provider but runs it inside docker

This keeps the core orchestrator unchanged.

## Why this is preferable to VMs
- faster startup
- easier resource sharing
- simpler portability
