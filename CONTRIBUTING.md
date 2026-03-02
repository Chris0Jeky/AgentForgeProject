# Contributing to AgentForge

## Development setup

- Python 3.11+
- git

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Running locally

```bash
agentforge --help
agentforge init
agentforge spawn --agent a1 --task demo
agentforge status
```

## Project structure

- `agentforge/cli.py`: CLI entrypoint
- `agentforge/core/*`: workspaces, policy, harness, daemon loop
- `agentforge/providers/*`: provider adapters (Codex CLI, shell, mock)
- `agentforge/templates/*`: files that `agentforge init` copies into repos
- `docs/*`: design and usage docs
- `examples/*`: sample configs and workflows

## PR guidelines

- Keep changes small, reviewable.
- Prefer stdlib and shelling out to `git/gh/docker` over heavy dependencies.
- Add docs updates for anything user-facing.
