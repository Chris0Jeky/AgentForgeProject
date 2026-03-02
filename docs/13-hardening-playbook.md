# Hardening playbook (incremental)

AgentForge intentionally starts “smooth” and becomes “strict” by adding gates.

This doc is a practical sequence that keeps usability high.

## Stage 0: Smooth local throughput (default)
- Use git worktrees (already).
- Use harness checks after changes (enable in config/policy).
- Use allowlisted PR commenters + strict command grammar (daemon).
- Deny fork PR automation.

## Stage 1: Sensitive paths
Turn protected paths from warn -> halt:
```toml
protect_globs = [".github/workflows/**"]
protect_behavior = "halt"
```

Forbid automation from touching:
```toml
forbid_globs = [".agentforge/**", ".git/**"]
```

## Stage 2: Separate roles physically
Run roles on different “lanes”:
- Implementer host: has toolchains but no secrets.
- Reviewer host: no credentials, optionally no network.
- Merge host: has release keys and merges PRs.

## Stage 3: Container sandbox runner
Run agents inside a container:
- mount only the worktree
- drop Linux capabilities
- use `--network none` for review roles

This prevents accidental writes outside workspace, and contains many classes of mistakes.

## Stage 4: Provenance and audit
- Write run summaries to `.agentforge/logs/*.json`
- Include commit trailers:
  - provider name
  - prompt hash
  - harness results summary

## Stage 5: Distributed scheduling
- add a central scheduler (SQLite/Redis)
- each host runs an agentforge worker that pulls jobs
- policy stays repo-local (checked in) but scheduler can set quotas

## What to avoid
- Running untrusted PR code on a persistent self-hosted runner with secrets.
- Accepting arbitrary commands from PR comments.
