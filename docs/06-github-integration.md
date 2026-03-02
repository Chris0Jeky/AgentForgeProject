# GitHub integration

AgentForge integrates with GitHub via the GitHub CLI (`gh`).

## Minimal mode: local polling daemon
- you run `agentforge daemon`
- it polls open PRs and reads comments
- it reacts only to allowlisted authors and strict command grammar

## Command protocol
Comments must be exactly:
- `/agentforge status`
- `/agentforge review`
- `/agentforge fix` + instructions

## Mapping PR -> workspace
The PR head branch name must follow:
- `af/<agent>/<task>`

This makes mapping deterministic, without extra bookkeeping.

## GitHub Actions wake workflow
AgentForge includes a template workflow that triggers on PR comments, but does not run anything sensitive.
You can extend it to run on a self-hosted runner at your own risk.
