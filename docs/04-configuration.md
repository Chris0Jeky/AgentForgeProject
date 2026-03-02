# Configuration

AgentForge uses two repo-local files:

- `.agentforge/config.toml`: project configuration
- `.agentforge/policy.toml`: governance and security gates

## config.toml keys

- `repo`: optional "owner/name" for gh integration
- `default_base_ref`: base for diffs and branch creation
- `worktrees_dir`: where worktrees live
- `compose_file`, `compose_profile`, `compose_project_prefix`: optional docker compose integration
- `harness_setup`, `harness_check`: lists of bash commands
- `default_provider`: default provider adapter
- `poll_interval_sec`: daemon poll loop interval

## policy.toml keys

- `mode`: "fast" or "safe"
- `allowed_comment_authors`: allowlist for PR commands
- `deny_forks`: refuse PR automation for fork PRs
- `forbid_globs`: paths automation must never modify
- `protect_globs`: paths that trip “manual review required”
- `max_changed_lines`: heuristic guard
- `require_harness_check`: run harness check after agent changes
- `allow_auto_commit` / `allow_auto_push`: gates for push automation
