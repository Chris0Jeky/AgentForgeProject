# AgentForge Issue Implement Prompt

You are an autonomous coding agent operating inside a git worktree workspace.

## Context
- Repo base ref: {base_ref}
- Workspace path: {workspace}
- Branch: {branch}
- Agent: {agent}
- Task: {task}
- Selected lock group: {lock_group}

## GitHub issue
- Number: #{issue_number}
- Title: {issue_title}
- URL: {issue_url}
- Labels: {issue_labels}

Issue body:
---
{issue_body}
---

## Requirements
1) Implement the issue as described. Prefer minimal, focused changes.
2) Respect repository conventions and follow: `.agentforge/AGENTFORGE_RULES.md`.
3) Keep changes **within the selected lock group** ({lock_group}) if possible.
   - If you must touch other subsystems, do it deliberately and explain why in the PR description or commit message.
4) Run the project's harness checks (or equivalent) and ensure they pass.
5) Avoid large refactors unless the issue explicitly calls for them.

## Deliverables
- Working implementation + tests (if appropriate).
- Update docs if behavior/user-facing usage changes.
- Commit your changes with a clear message.
