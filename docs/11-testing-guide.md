# Testing Guide

This project currently uses smoke tests and command-level validation.
The steps below avoid major changes and are focused on confidence checks.

## 1) Environment Check

From repo root:

```bash
python --version
git --version
```

Optional tools for extra paths:

```bash
gh --version
codex --version
```

## 2) Install In Editable Mode

```bash
python -m venv .venv
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1
# Bash:
# source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

## 3) Basic Import And CLI Smoke Checks

```bash
python -c "import agentforge; import agentforge.cli; import agentforge.core.config; print(agentforge.__version__)"
agentforge --help
agentforge init --help
agentforge spawn --help
agentforge run --help
agentforge daemon --help
```

## 3.5) Run Unit Tests

```bash
python -m pytest -q
```

## 4) Workspace Lifecycle Smoke Test (Low Risk)

This test exercises `spawn -> run(mock) -> status -> rm`.

```bash
agentforge init
agentforge spawn --agent smoke --task smoke-test
agentforge run --agent smoke --task smoke-test --provider mock --role implement --prompt "smoke test"
agentforge status
agentforge rm --agent smoke --task smoke-test --delete-branch
```

Notes:

- `spawn` runs `git fetch origin --prune`, so `origin` should exist.
- `mock` provider is deterministic and does not call external services.

## 5) Harness Check Validation

After you set real commands in `.agentforge/config.toml`:

```bash
agentforge harness --agent <agent> --task <task> --step setup
agentforge harness --agent <agent> --task <task> --step check
```

Keep harness commands idempotent and close to CI behavior.

## 6) Daemon Validation (Optional)

Prerequisites:

- `.agentforge/config.toml` has `repo = "owner/name"`
- `gh auth status` is healthy
- your username is in `allowed_comment_authors`

Run:

```bash
agentforge daemon --once
```

Then validate behavior with PR comments:

- `/agentforge status`
- `/agentforge review`
- `/agentforge fix <instructions>`

## 7) Failure Triage Checklist

1. Check `.agentforge/config.toml` and `.agentforge/policy.toml`.
2. Confirm repo has valid `origin` and base ref.
3. Confirm provider binary exists (`codex`, `gh`, etc.).
4. Inspect local terminal output around `run` or `daemon`.
5. Re-run using `--provider mock` to separate orchestration issues from provider issues.
