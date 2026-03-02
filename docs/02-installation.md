# Installation

AgentForge aims to be installable anywhere Python 3.11+ runs.

## Option A: pipx (recommended)
If you have pipx installed:

```bash
pipx install .
# or pipx install git+https://github.com/<you>/agentforge
```

## Option B: venv dev install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Prerequisites
- `git` (required)
- Optional:
  - `docker` + `docker compose` (for runtime stacks)
  - GitHub CLI `gh` (for PR comment automation)
  - Codex CLI `codex` (if using Codex adapter)

AgentForge works without optional tools; you just won’t use those features.
