# Roadmap

This repo is intentionally a strong skeleton. Suggested milestones:

## Milestone 1: Solid local workflows
- finish provider adapters (codex stable)
- add `agentforge pr create`
- add `agentforge issue claim` (labels / status)
- add better logs and run summaries

## Milestone 2: Conflict avoidance
- per-directory locks (backend/frontend/docs)
- diff overlap detector across worktrees

## Milestone 3: Secure automation
- container sandbox runner
- reviewer lane with anomaly detection
- signed provenance metadata in commits

## Milestone 4: Scaling out
- multi-host scheduler
- remote docker contexts
- optional web UI
