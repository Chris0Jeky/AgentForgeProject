# Security model and hardening

AgentForge’s philosophy is “smooth by default, hardenable over time”.

## Threat model (practical)
If you allow PR comments to trigger automation, treat them as an attack surface:
- an attacker can try to get your host to run arbitrary code
- they can also try to get your agent to introduce malicious changes

## Recommended baseline
- strict command grammar (no arbitrary shell commands from comments)
- allowlisted command authors only
- deny fork PR automation
- tripwires on high-risk paths (`.github/workflows/**`) and suspicious patterns (`curl | sh`)
- run agents inside disposable worktrees (so reverting is easy)

## Hardening options (incremental)
1) Run the daemon on a machine with minimal secrets.
2) Use a separate OS user for the daemon.
3) Run agents inside containers with:
   - only the worktree mounted
   - reduced capabilities
   - optional network restriction for certain roles (reviewer)

4) Add a “reviewer lane” that never reads external PR comments:
   - it only reviews diffs and flags anomalies

5) Add a git hook or server-side check:
   - forbid high-risk file paths in agent branches
   - require CI green

## About self-hosted runners
If you later connect this to GitHub Actions with self-hosted runners, treat that as higher risk.
Prefer a “wake-only” workflow that triggers a local poll cycle over running untrusted code with secrets.
