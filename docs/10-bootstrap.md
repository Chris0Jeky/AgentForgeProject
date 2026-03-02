# Bootstrap (queue intake)

AgentForge supports a “queue -> worktrees -> PRs” pipeline via `agentforge bootstrap`.

## Why labels?

Labels are a low-friction state machine:
- queued label: candidates to pick up
- in-progress label: claimed
- done label: merged/finished

You can keep this compatible with more advanced systems (GitHub Projects, Jira, Taskdeck board) later.

## Command

```bash
agentforge bootstrap --agents a1,a2 --take 2 --claim --fast --create-prs
```

Flags:
- `--agents a1,a2,a3`: agent ids used for assignment
- `--take N`: number of issues from queue
- `--claim`: move labels and post a claim comment
- `--fast`: actually run implementer agents + auto push
- `--create-prs`: open draft PRs after push
- `--daemon`: start PR comment daemon afterwards (blocks)

## Safety notes

- `policy.toml` controls who can command the daemon and whether fork PRs are allowed.
- The diff scanner halts on high-risk changes (workflow edits, curl|sh patterns, secret-like strings).
- `protect_behavior = "warn"` keeps things smooth but visible; switch to `"halt"` when you harden.
