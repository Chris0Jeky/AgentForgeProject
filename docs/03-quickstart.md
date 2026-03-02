# Quickstart

## 1) Initialize AgentForge in a repo

```bash
cd /path/to/your/repo
agentforge init
```

This creates `.agentforge/` with:
- `config.toml` (repo configuration)
- `policy.toml` (automation policy)
- `AGENTFORGE_RULES.md` (prompt guardrails)
- `workflows.toml` (workflow definitions)
- `locks.toml` (lock group metadata for auto-routing)
- `mcp.toml` (optional MCP config)
- `prompts/issue_implement.md` (prompt template used by the default workflows)

## 2) Edit `.agentforge/config.toml`

Set:
- `repo = "owner/name"` (if you want GitHub automation)
- harness commands (setup/check)
- optional compose integration
- `default_workflow` and `auto_lock_strategy` if you want `bootstrap` auto-routing

## 3) Add allowed commenters

Edit `.agentforge/policy.toml`:

```toml
allowed_comment_authors = ["your-github-username"]
```

## 4) Spawn workspaces

```bash
agentforge spawn --agent a1 --task issue-123
agentforge spawn --agent a2 --task issue-456
```

## 5) Run a workflow

```bash
agentforge workflow run --workflow default --agent a1 --task issue-123
```

## 6) UI dashboard

```bash
agentforge serve        # read-only
agentforge ui           # actions-enabled (token printed)
```

## 7) Run the daemon (optional)

```bash
agentforge daemon
```

Then, on a PR whose branch is named `af/<agent>/<task>`, you can post a PR comment:

- `/agentforge review`
- `/agentforge fix` + instructions

AgentForge will react locally.
