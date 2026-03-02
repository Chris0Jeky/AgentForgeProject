# AgentForge

AgentForge is a **local-first** “agent farm” you can install on any machine to run multiple coding agents **without stepping on each other**.

Core ideas:
- **Isolation** via `git worktree` (one task = one directory = one branch).
- **Automation** via a strict orchestrator:
  - spawn worktrees,
  - run an agent provider (Codex CLI today, others via plugins),
  - run a repo harness (tests/lint/build),
  - respond to GitHub PR comment commands safely.

AgentForge aims to be:
- **smooth** in “fast mode” (minimal interruptions),
- **recoverable** (agents work in disposable worktrees),
- **hardenable** (policy-as-code + diff scanners + role separation).

---

## Install

Prereqs:
- Python 3.11+
- git
- Optional:
  - GitHub CLI `gh` (queue + PR + daemon)
  - Codex CLI `codex` (if using codex provider)
  - Docker (only if you later add a stack runner)

Dev install:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Quickstart (per repo)

Initialize in a repo:
```bash
cd /path/to/your/repo
agentforge init
```

Edit:
- `.agentforge/config.toml` (harness commands + repo name)
- `.agentforge/policy.toml` (allowed commenters, deny forks, etc.)

Spawn a workspace:
```bash
agentforge spawn --agent a1 --task issue-123
```

Run an agent:
```bash
agentforge run --agent a1 --task issue-123 --role implement \
  --provider codex_cli --auto-commit --auto-push \
  --prompt "Fix issue-123 and run harness checks."
```

---

## One-command intake (queue bootstrap)

If you use GitHub issue labels as a queue:

- queued: `agent:queued`
- in-progress: `agent:in-progress`

Run:
```bash
agentforge bootstrap --agents a1,a2 --take 2 --claim --fast --create-prs
```

What it does:
- pulls queued issues
- spawns worktrees
- claims issues (label move + comment)
- runs implementer agent for each
- auto-commits + pushes
- creates draft PRs

---

## PR comment automation

Run locally:
```bash
agentforge daemon
```

On a PR whose head branch is named `af/<agent>/<task>`, comment:

- `/agentforge status`
- `/agentforge review`
- `/agentforge qa`
- `/agentforge fix` + instructions

---

## GitHub Actions trigger (optional)

You can run AgentForge on a self-hosted runner by passing the event payload to:

```bash
agentforge webhook --event-file "$GITHUB_EVENT_PATH"
```

See docs for the security tradeoffs and recommended “wake-only” setups.

---

## Dashboard (UI)

Read-only local dashboard:

```bash
agentforge serve
# open http://127.0.0.1:5179/
```

Actions-enabled UI (workspace spawning, locks, workflow runs):

```bash
agentforge ui
# prints a URL with a token:
#   http://127.0.0.1:5179/?token=...
```

MCP management (optional, via Docker MCP Toolkit):

```bash
agentforge mcp status
agentforge mcp catalog --filter playwright
agentforge mcp sync
```

## Docs

See `docs/` for architecture, security, harness, provider plugins, and roadmap.
