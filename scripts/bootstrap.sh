#!/usr/bin/env bash
set -euo pipefail

# Example:
#   AGENTS=a1,a2 TAKE=2 agentforge bootstrap --claim --fast --create-prs
AGENTS="${AGENTS:-a1,a2}"
TAKE="${TAKE:-2}"

exec agentforge bootstrap --agents "$AGENTS" --take "$TAKE" --claim --fast --create-prs
