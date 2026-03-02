# Quickstart

## 1) Initialize AgentForge in a repo

```bash
cd /path/to/your/repo
agentforge init
```

This creates `.agentforge/` with:
- config.toml (repo configuration)
- policy.toml (automation policy)
- AGENTFORGE_RULES.md (prompt guardrails)
- a sample GitHub “wake” workflow (optional)

## 2) Edit `.agentforge/config.toml`

Set:
- repo = "owner/name" (if you want GitHub automation)
- harness commands (setup/check)
- optional compose integration

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

## 5) Run an implementer agent
```bash
agentforge run --agent a1 --task issue-123 --role implement --provider codex_cli --prompt "Implement issue-123."
```

## 6) Run the daemon (optional)
```bash
agentforge daemon
```

Then, on a PR whose branch is named `af/<agent>/<task>`,
you can post a PR comment:
- `/agentforge review`
- `/agentforge fix` + instructions

AgentForge will react locally.
