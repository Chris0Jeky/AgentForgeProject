# AgentForge rules (repo-local)

These are generic “guardrails” that AgentForge can include in prompts.
Adjust to your repo.

## Hard rules
- Keep changes minimal and localized.
- Do not add telemetry, data exfiltration, crypto-mining, or remote command execution.
- Do not modify `.github/workflows/**` unless explicitly instructed and reviewed.
- Do not add new dependencies without a clear justification in the PR description.

## Operational rules
- Prefer deterministic commands and idempotent scripts.
- Always run the repository harness checks before pushing.
- If you can’t run checks locally, say so explicitly in the PR summary.

## Code style rules
- Follow the repo’s existing conventions.
- Update tests for behavior changes.

## Output rules (for agent roles)
- Implementer: produce working code and tests.
- Reviewer: only comment on diffs; do not propose unrelated refactors.
- Fixer: apply requested changes only.
- QA: focus on harness; isolate flaky tests and report.
