# TODOs, Placeholders, and Skeleton Gaps

This file documents unfinished or intentionally generic areas in the current codebase.

## 1) Explicit TODO/FIXME/TBD markers

Search result: none found in `agentforge/`, `scripts/`, and `examples/` for:

- `TODO`
- `FIXME`
- `TBD`
- `XXX`

This means most pending work is represented as placeholders/defaults and extension hooks, not literal TODO comments.

## 2) Action-Required Placeholders (Configure Before Real Use)

1. GitHub repo is blank by default.
   - `agentforge/templates/config.toml:5` -> `repo = ""`
   - Impact: daemon GitHub integration cannot run until set.

2. Comment author allowlist is a placeholder.
   - `agentforge/templates/policy.toml:11`
   - `agentforge/templates/policy.toml:12` -> `# "your-github-username"`
   - Impact: PR command automation should not be enabled until this is populated.

3. Harness commands are template stubs.
   - `agentforge/templates/config.toml:28` -> `harness_setup = [`
   - `agentforge/templates/config.toml:31` -> `harness_check = [`
   - Impact: `run`/`harness` checks provide little value until repo-specific commands are defined.

4. Compose integration is placeholder/optional by default.
   - `agentforge/templates/config.toml:22` -> `compose_file = ""`
   - `agentforge/templates/config.toml:23` -> `compose_profile = ""`
   - Impact: no per-workspace service stack unless configured.

## 3) Implementation Gaps (Functioning Skeleton, Not Fully Wired)

1. Policy fields parsed but not enforced in diff gate logic.
   - Declared and loaded:
     - `agentforge/core/config.py:55` (`forbid_globs`)
     - `agentforge/core/config.py:56` (`protect_globs`)
     - `agentforge/core/config.py:57` (`max_changed_lines`)
     - `agentforge/core/config.py:122-124` (load from TOML)
   - Only shown in summary output:
     - `agentforge/core/policy.py:19`
   - Not consumed by `scan_diff()`/runner gating today.
   - Current scan uses hardcoded patterns and threshold:
     - `agentforge/core/diffscan.py:15` (`HIGH_RISK_FILE_PATTERNS`)
     - `agentforge/core/diffscan.py:21` (`HIGH_RISK_CONTENT_PATTERNS`)
     - `agentforge/core/diffscan.py:52` (`lines > 5000`)

2. Compose config is only partially used.
   - Only `compose_file` gates whether a project name is generated:
     - `agentforge/core/workspace.py:71`
   - `compose_profile` is loaded but not used by runtime commands.
   - Impact: compose settings are informational unless you add stack orchestration commands.

3. Runner role prompts are intentionally minimal and expected to be customized.
   - `agentforge/core/runner.py:46` comment: `minimal; extend in your project`
   - Role branches:
     - `agentforge/core/runner.py:47` (`review`)
     - `agentforge/core/runner.py:55` (`qa`)
     - `agentforge/core/runner.py:61` (`fix`)
     - `agentforge/core/runner.py:67` (`implement`)

4. Daemon command surface is intentionally narrow.
   - Strict grammar:
     - `agentforge/core/daemon.py:20`
   - Supported commands:
     - `help`: `agentforge/core/daemon.py:47`
     - `status`: `agentforge/core/daemon.py:56`
     - `review`: `agentforge/core/daemon.py:75`
     - `fix`: `agentforge/core/daemon.py:84`
   - Impact: no built-in queue/claim/bootstrap/pr-create command flow yet.

5. CLI command set is skeleton-level (core operations only).
   - Registered commands:
     - `agentforge/cli.py:120` (`init`)
     - `agentforge/cli.py:124` (`spawn`)
     - `agentforge/cli.py:130` (`list`)
     - `agentforge/cli.py:133` (`rm`)
     - `agentforge/cli.py:139` (`status`)
     - `agentforge/cli.py:142` (`harness`)
     - `agentforge/cli.py:148` (`run`)
     - `agentforge/cli.py:159` (`daemon`)
   - Impact: no first-class `bootstrap`, `queue`, or `pr create` command yet.

6. Workspace spawn assumes an `origin` remote exists.
   - `agentforge/core/workspace.py:62` runs `git fetch origin --prune`
   - Impact: fails in repos without `origin` or in offline scenarios.

## 4) Example-Specific Placeholders

1. Generic node example still needs repo identity.
   - `examples/generic-node/.agentforge/config.toml:1` -> `repo = ""`

2. Taskdeck example is intentionally hardcoded to a specific repo/account.
   - `examples/taskdeck/.agentforge/config.toml:3` -> `repo = "Chris0Jeky/Taskdeck"`
   - `examples/taskdeck/.agentforge/policy.toml:3` -> fixed `allowed_comment_authors`
   - Impact: copy this example only after replacing org/user values.

## 5) Suggested Order To Address

1. Fill `repo`, `allowed_comment_authors`, and harness commands.
2. Decide whether compose support is needed now; if yes, wire `compose_profile` and lifecycle commands.
3. Wire `forbid_globs`/`protect_globs`/`max_changed_lines` into `scan_diff` policy enforcement.
4. Add next CLI capabilities (`bootstrap`, queue intake, PR creation) if desired.
