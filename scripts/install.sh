#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
echo "Installed AgentForge into .venv. Run: source .venv/bin/activate && agentforge --help"
