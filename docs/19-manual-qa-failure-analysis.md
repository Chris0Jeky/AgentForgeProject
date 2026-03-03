# Manual QA Failure Analysis and Recovery Plan (2026-03-03)

This document captures the failures seen in the manual terminal/UI run and the strategy to stabilize the product.

## 1) Observed failures

### A) Git/worktree commands failed with `\cygdrive\...` paths

Symptoms:
- `agentforge init` printed repo root like `\cygdrive\c\...`
- `spawn` / `bootstrap` failed with:
  - `fatal: not a git repository (or any parent up to mount point /cygdrive)`
  - `Command failed (128): git worktree add ... \cygdrive\...`

Root cause:
- On some Windows shells/toolchains, `git rev-parse --show-toplevel` returns POSIX-style roots (`/cygdrive/c/...` or `/c/...`).
- AgentForge was treating that value as a Windows path directly, producing invalid cwd/path arguments for subprocess git calls.

Fix:
- Added path normalization in repo root detection:
  - `/cygdrive/c/...` -> `C:/...`
  - `/c/...` -> `C:/...`
- Non-Windows platforms are unaffected.

Validation:
- Spawn/rm lifecycle works with normalized Windows paths.
- Added regression tests:
  - `tests/test_config_paths.py`

### B) UI tabs not switching

Symptoms:
- UI loaded but tabs were non-functional.

Root cause:
- Inline UI JavaScript string generation embedded raw newlines into JS string literals.
- This produced invalid JS syntax in the page script and broke runtime behavior.

Fix:
- Escaped newline literals correctly in generated JS (`"\\n"` instead of `"\n"` in Python source context).

Validation:
- Extracted page script passes `node --check`.
- UI endpoint script now parses successfully.

### C) `daemon --once` said repo not configured

Symptoms:
- `GitHub repo not configured. Set repo = "owner/name" ...`

Root cause:
- `.agentforge/config.toml` had `repo = ""` (expected template default).

Fix:
- Set explicit repo value in local config for QA runs:
  - `repo = "Chris0Jeky/AgentForgeProject"`

### D) `qa_mock` workflow missing

Symptoms:
- `Workflow not found: qa_mock. Available: backend, default, docs, frontend`

Root cause:
- `qa_mock` was a local QA convenience workflow but not present in default templates/config.

Fix:
- Added `workflow.qa_mock` to:
  - `agentforge/templates/workflows.toml`
  - `.agentforge/workflows.toml`

### E) Harness used Git Bash Python instead of active Windows venv

Symptoms:
- Workflow step invoked `bash -lc python -m pytest -q` on Windows.
- Tests ran under a different Python runtime (`/usr/lib/python3.11`) than the active `.venv`.

Root cause:
- Shell resolution always preferred `bash`/`sh`, even on Windows.

Fix:
- Made shell selection platform-aware:
  - Windows: prefer `pwsh` / `powershell`, then `bash`/`sh`.
  - Non-Windows: keep `bash`/`sh` first.

Validation:
- `pytest` passes in both:
  - native invocation (`python -m pytest -q`)
  - `bash -lc "python -m pytest -q"`
- Added regression tests:
  - `tests/test_shell_cmd.py`

### F) Existing worktree metadata broken across mixed Git toolchains

Symptoms:
- Existing workspace runs failed with:
  - `fatal: not a git repository: .../.git/worktrees/<name>`
- `.worktrees/<name>/.git` pointed to `/cygdrive/...` style paths.

Root cause:
- Worktree metadata was created with path style from one Git toolchain and consumed by another.

Fix:
- Added best-effort `git worktree repair <workspace>` immediately after spawn.
- Also used manual repair once for pre-existing workspaces:
  - `git worktree repair <workspace-path>`

Validation:
- New workspaces now get canonical `gitdir: C:/...` pointers and run workflows correctly.

### G) `codex_cli` provider could fail on Windows npm installs

Symptoms:
- `agentforge run --provider codex_cli ...` failed with `FileNotFoundError` even when `codex` existed.

Root cause:
- Provider checked `which("codex")` but still executed bare `codex`.
- On some Windows setups this resolves to npm launchers (`codex.cmd`) that require explicit command resolution.

Fix:
- `codex_cli` now resolves and executes the concrete binary path:
  - prefers `codex.cmd`, then `codex.exe`, then `codex`.
  - wraps `.cmd`/`.bat` with `cmd /c ...`.
- Added regression tests:
  - `tests/test_provider_codex_cli.py`

## 2) Stabilization strategy

### Phase 1: Environment reliability

1. Ensure editable install is current:
   - `python -m pip install -e .[dev]`
2. Verify config:
   - `.agentforge/config.toml` has `repo` and `harness_check`.
   - `.agentforge/policy.toml` has allowlisted comment authors.
3. Verify root and spawn:
   - `agentforge spawn --agent smoke --task smoke-test`
   - `agentforge rm --agent smoke --task smoke-test --delete-branch`

Exit criteria:
- No path-format related git errors.

### Phase 2: UI and async run reliability

1. Start UI:
   - `python -m agentforge.cli ui`
2. Verify:
   - tab switching works
   - queue and run panels load
   - run stream endpoint emits events

Exit criteria:
- UI script loads with no blocking syntax/runtime errors.

### Phase 3: Workflow and daemon behavior

1. Deterministic local workflow:
   - `python -m agentforge.cli workflow run --workflow qa_mock --agent qa1 --task issue-5`
2. Queue/bootstrap smoke:
   - `python -m agentforge.cli queue list --limit 10`
   - `python -m agentforge.cli bootstrap --agents qa1,qa2 --take 2`
3. Daemon parser smoke:
   - `python -m agentforge.cli daemon --once`

Exit criteria:
- predictable workflow execution
- no parser regressions
- no lock/workspace leaks after cleanup

### Phase 4: Codex E2E path (real code change -> commit -> push -> PR)

1. Confirm prerequisites in the same terminal where you run AgentForge:
   - `where git`
   - `where codex`
   - `gh auth status`
2. Spawn a dedicated smoke workspace:
   - `agentforge spawn --agent demo --task codex-smoke`
3. Run Codex implementer with auto commit/push:
   - `agentforge run --agent demo --task codex-smoke --role implement --provider codex_cli --auto-commit --auto-push --prompt "<small, concrete edit request>"`
4. Create PR:
   - `agentforge pr create --agent demo --task codex-smoke --title "[demo] codex smoke" --body "Automated codex smoke run"`
5. Optional: run daemon one-shot to validate command loop:
   - `agentforge daemon --once`

Exit criteria:
- branch pushed to origin
- PR exists
- harness and guardrails passed

## 3) Ongoing QA recommendations

1. Keep `qa_mock` as the first-line regression workflow for local manual QA.
2. Run both:
   - `python -m unittest discover -s tests -v`
   - `python -m pytest -q`
3. Add a lightweight UI smoke test in CI later (headless browser) for tab navigation and core API wiring.
4. Keep path normalization tests to prevent regressions in mixed shell environments on Windows.
5. Keep manual smoke tasks in GitHub (`agent:test`) so queue/bootstrap runs are deterministic.
