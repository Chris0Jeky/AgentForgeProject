# AGENTS.md

These are repository-specific working agreements for coding agents (Codex, Claude, Gemini, local, etc.).

## Ground rules
- Stay inside the repository/worktree unless explicitly instructed otherwise.
- Prefer minimal, focused diffs. Avoid broad refactors unless required.
- Never modify security-sensitive paths (e.g. `.github/workflows/**`, auth/token handling) without calling it out in the final summary.
- If you must introduce a new dependency, explain why and keep it dev-only when possible.

## How to work in this repo
- Run unit tests before claiming completion:
  - `pip install -e .[dev]`
  - `pytest -q`
- Keep Python compatibility: 3.11+.
- Keep runtime dependencies minimal (prefer stdlib). Dev tooling can live in optional extras.
- If a task prompt explicitly says `Only edit ...` (or otherwise constrains files/commands), treat that as a hard override:
  - edit only the named files
  - skip broad repo discovery
  - skip install/test commands unless explicitly requested in that task
  - AgentForge will run post-edit harness checks separately

## Architectural expectations
- Core logic lives under `agentforge/core`.
- Provider adapters live under `agentforge/providers`.
- CLI wiring lives in `agentforge/cli.py`.
- Keep changes testable; add/adjust tests in `tests/`.

## Guardrails for automation
- When adding new automation triggers, keep the command grammar strict.
- Never execute arbitrary shell snippets from untrusted sources (PR comments, issue text, etc.).
- Prefer GitHub API/CLI calls that are scoped to the configured repo.
