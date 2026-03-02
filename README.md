# AgentForge

AgentForge is a **local-first** “agent farm” you can install on any machine to run multiple coding agents **without stepping on each other**.

Core ideas:
- **Code isolation** via `git worktree` (one task = one directory = one branch).
- **Runtime isolation** (optional) via Docker Compose project scoping + per-agent ports.
- **Automation** via a simple orchestrator that can:
  - spawn worktrees,
  - run agents (Codex CLI today; others via plugins),
  - run project harness checks,
  - react to GitHub PR comment commands.

AgentForge is meant to be:
- **fast** in “free mode” (minimal approvals),
- **recoverable** (agents are contained in disposable worktrees),
- and **hardenable** over time (policy gates, diff scanners, least-privilege GitHub triggers).

> Status: usable skeleton + working CLI foundation. Expect to extend it to your workflow.

---

## Quickstart (local, no GitHub automation)

Prereqs:
- Python 3.11+
- git
- (optional) docker + docker compose
- (optional) GitHub CLI `gh`

Install (editable dev install):
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Initialize in a repo:
```bash
cd /path/to/your/repo
agentforge init
```

Spawn a new isolated workspace:
```bash
agentforge spawn --agent a1 --task issue-123
```

Run an agent in that workspace (example uses Codex CLI):
```bash
agentforge run --agent a1 --task issue-123 --role implement --provider codex_cli --prompt "Fix issue-123. Run tests. Open a PR."
```

---

## GitHub comment commands (optional)

AgentForge supports a strict command grammar from PR comments:

- `/agentforge status`
- `/agentforge review`
- `/agentforge fix` (takes the rest of the comment as instructions)

Run a polling daemon:
```bash
agentforge daemon
```

> You must configure allowed commenters in `.agentforge/policy.toml`.

---

## Docs

See `docs/`:
- `01-overview.md` (architecture)
- `03-quickstart.md` (end-to-end flows)
- `05-security.md` (threat model + hardening)
- `07-providers.md` (add Gemini/Claude/local via plugins)
- `10-porting-notes.md` (what was ported and why)
- `11-testing-guide.md` (smoke tests and validation workflow)
- `12-todos-placeholders.md` (tracked placeholders and implementation gaps)

---

## Philosophy

**Smooth by default** (your preference): the system will auto-run unless a policy tripwire is hit.
Tripwires are explicit, testable, and versioned as policy-as-code.

---

## Contributing

See `CONTRIBUTING.md`.
