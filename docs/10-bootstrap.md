# Bootstrap (queue intake)

`agentforge bootstrap` is the “queue -> worktrees -> workflow -> PR” pipeline.

It is designed for scaling to multiple parallel agents while avoiding merge conflicts and resource collisions.

---

## Why labels?

Labels are a low-friction state machine:
- queued label: candidates to pick up
- in-progress label: claimed
- done label: merged/finished

You can keep this compatible with GitHub Projects / Jira / Taskdeck later.

---

## Command

```bash
agentforge bootstrap --agents a1,a2 --take 2 --claim --fast --create-prs
```

Flags:
- `--agents a1,a2,a3`: agent IDs used for assignment
- `--take N`: number of issues from queue (AgentForge will prefer issues mapping to different lock groups)
- `--claim`: move labels and post a claim comment
- `--fast`: run the selected workflow for each issue
- `--create-prs`: create PRs (workflows can gate PR steps via `{create_prs}`)
- `--no-draft`: create non-draft PRs (workflows can use `{draft_prs}`)
- `--workflow NAME`: force a workflow for all selected issues (overrides auto-routing)
- `--daemon`: start PR comment daemon afterwards (blocks)

---

## Auto-routing via locks.toml

When bootstrapping from GitHub issues, AgentForge can auto-select:
- a **lock group**
- a **workflow**

using `.agentforge/locks.toml` + `.agentforge/config.toml`:

- `locks.toml` group entries can define `labels`, `keywords`, `workflow`, and `priority`.
- `config.toml` sets `auto_lock_strategy` and `default_workflow`.

This lets you run multiple agents in parallel without them hammering the same subsystem.

---

## Injected workflow context

When `bootstrap` runs a workflow it injects:

- `{issue_number}` `{issue_title}` `{issue_url}`
- `{issue_labels}` `{issue_body}`
- `{lock_group}`
- `{create_prs}` `{draft_prs}`

so your workflows and prompt templates can be issue-aware.

---

## Safety notes

- `policy.toml` controls who can command the daemon and whether fork PRs are allowed.
- The diff scanner halts on high-risk changes (workflow edits, curl|sh patterns, secret-like strings).
- `protect_behavior = "warn"` keeps things smooth but visible; switch to `"halt"` when you harden.
