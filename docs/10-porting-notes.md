# Porting Notes (Archive -> AgentForgeProject)

This repository was ported from:

- `Archive/agentforge`

The port goal was to keep behavior stable and make only small, low-risk adjustments.

## What Was Ported

The following were copied into this repo:

- Python package: `agentforge/`
- Docs: `docs/01-...09` and `docs/diagrams.md`
- Scripts: `scripts/`
- Examples: `examples/`
- Project metadata: `pyproject.toml`, `README.md`, `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`

## Small Adjustments Applied

1. Replaced root `.gitignore` with a practical Python + Bash + AgentForge runtime ignore list.
2. Removed the placeholder `main.py` that came from an IDE starter template.
3. Kept runtime logic and command behavior unchanged unless explicitly documented elsewhere.

## How The Code Is Organized

- `agentforge/cli.py`
  - CLI entrypoint and command wiring.
  - Commands: `init`, `spawn`, `list`, `rm`, `status`, `harness`, `run`, `daemon`.

- `agentforge/core/config.py`
  - Finds repo root and loads `.agentforge/config.toml` and `.agentforge/policy.toml`.
  - Defines `RepoConfig` and `Policy`.

- `agentforge/core/init.py`
  - Initializes `.agentforge/` and copies templates.

- `agentforge/core/workspace.py`
  - Creates/removes git worktree workspaces.
  - Allocates per-workspace port and writes `.agentforge.env`.

- `agentforge/core/state.py`
  - Reads/writes state file and uses a lock file for cross-process coordination.

- `agentforge/core/harness.py`
  - Runs configured setup/check commands in workspace context.

- `agentforge/core/runner.py`
  - Executes provider role (`implement`, `review`, `fix`, `qa`).
  - Runs diff scan and optional harness gate.
  - Optionally auto-commits and auto-pushes.

- `agentforge/core/diffscan.py`
  - Simple tripwires for high-risk file paths and content patterns.

- `agentforge/core/github.py` and `agentforge/core/daemon.py`
  - Polls PR comments via `gh`.
  - Handles strict `/agentforge ...` command grammar.
  - Enforces allowlist and fork policy checks.

- `agentforge/providers/*`
  - `codex_cli`: runs `codex exec`.
  - `shell`: runs a shell command.
  - `mock`: deterministic provider for smoke tests.

## Why This Design Works

The key invariant is:

- `1 task == 1 worktree == 1 branch == 1 directory`

This avoids branch and filesystem collisions while keeping local throughput high.

## Next Extension Points

If you continue from the memo roadmap, the next low-risk features are:

1. `agentforge bootstrap` (`init + spawn + daemon` orchestration)
2. Optional issue queue intake (`gh issue list` + claim flow)
3. Optional PR creation command once `run` succeeds
