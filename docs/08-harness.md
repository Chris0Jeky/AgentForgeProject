# Harness design (important)

The harness is what prevents “agent drift” from silently breaking the repo.

In AgentForge:
- `harness_setup`: idempotent commands to prepare workspace
- `harness_check`: required verification commands (tests, lint, build)

Best practice:
- keep `harness_check` as close to CI as possible
- if some checks are slow, separate into quick/slow tiers
- set explicit concurrency (e.g. dotnet `-m:1`) if the repo is sensitive to parallelism

AgentForge runs harness checks after agent roles that modify code (implement/fix),
unless disabled in policy.
