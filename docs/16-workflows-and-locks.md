# Workflows and locks

This doc explains the two scaling primitives in AgentForge:

- `.agentforge/workflows.toml`: a tiny workflow engine
- `.agentforge/state/locks/*.lock.json`: a simple subsystem exclusivity mechanism

---

## Workflows

File: `.agentforge/workflows.toml`

Run:

```bash
agentforge workflow run --workflow default --agent a1 --task issue-123
```

### Why workflows?

They provide a stable, repo-local automation pipeline without rewriting Python:

- run implementer agent
- run harness
- open PR
- post summary comment
- etc.

### Step types

See the template file for the current set.

Notable features:
- **templating** in strings (e.g. PR title/body, prompts, lock group)
- optional step gating via `enabled=...` (boolean or template string)
  - useful for toggling PR creation in `bootstrap` via `{create_prs}`

---

## Locks

Lock directory:
- `.agentforge/state/locks/*.lock.json`

Acquire:

```bash
agentforge lock acquire --group frontend --agent a1 --task issue-123
```

Release:

```bash
agentforge lock release --group frontend --agent a1 --task issue-123
```

List:

```bash
agentforge lock list
```

### How locks prevent stepping on toes

If you enforce a convention like:

- backend tasks acquire `backend`
- frontend tasks acquire `frontend`

…then only one active workflow can hold that subsystem at a time on the host.

This reduces:
- expensive merge conflicts (two PRs racing in the same area)
- resource contention (ports, local caches, etc.)

### TTL and stealing

Locks have TTLs to reduce “stuck” situations.

- expired locks can be stolen automatically
- `--force` can steal immediately

---

## locks.toml metadata (auto-routing)

`.agentforge/locks.toml` is optional metadata that helps automation decide:
- which lock group to use for a GitHub issue
- which workflow to run for that lock group

This is primarily consumed by `agentforge bootstrap`, but you can also use it as a canonical
“subsystem ownership map” for humans.

---

## Recommended default

- Start with locks on the most conflict-prone areas (frontend/back).
- Keep `protect_behavior="warn"` initially, then move to `"halt"` as you harden.
