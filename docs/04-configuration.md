# Configuration

AgentForge uses repo-local config files under `.agentforge/`.

Required:
- `.agentforge/config.toml`: project configuration
- `.agentforge/policy.toml`: governance and security gates

Optional (but useful):
- `.agentforge/workflows.toml`: workflow definitions
- `.agentforge/locks.toml`: lock group metadata (auto-routing)
- `.agentforge/mcp.toml`: MCP management (Docker MCP Toolkit)

---

## config.toml keys

Core:
- `repo`: optional `"owner/name"` for gh integration
- `default_base_ref`: base for diffs and branch creation
- `worktrees_dir`: where worktrees live
- `compose_file`, `compose_profile`, `compose_project_prefix`: optional docker compose integration
- `harness_setup`, `harness_check`: lists of shell commands
- `default_provider`: default provider adapter

Workflow defaults:
- `default_workflow`: workflow name to run when none is selected
- `auto_lock_strategy`: how `bootstrap` selects a lock group
  - `none | labels | keywords | labels_then_keywords`

Daemon:
- `poll_interval_sec`: PR comment poll loop interval

Queue:
- `queue_label`, `in_progress_label`, `done_label`: label state machine

---

## policy.toml keys

- `mode`: `"fast"` or `"safe"`
- `allowed_comment_authors`: allowlist for PR commands (daemon/webhook)
- `deny_forks`: refuse PR automation for fork PRs
- `forbid_globs`: paths automation must never modify
- `protect_globs`: paths that trip “manual review required”
- `max_changed_lines`: heuristic guard
- `require_harness_check`: run harness check after agent changes
- `allow_auto_commit` / `allow_auto_push`: gates for push automation
