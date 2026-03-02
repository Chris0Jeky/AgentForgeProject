# Providers

A Provider is the only part of AgentForge that is “agent-specific”.

Interface:
- input: (prompt, cwd, env)
- output: success/failure

Built-ins:
- `codex_cli`: shells out to `codex exec`
- `shell`: runs a shell command (useful for local tooling)
- `mock`: deterministic provider for demos/tests

## Adding Claude/Gemini/local models
You have two main routes:

1) CLI wrapper
- install the vendor CLI
- implement Provider.run by shelling out

2) API adapter
- use their SDK
- add optional dependencies
- keep secrets out of repo (env vars / secret manager)

Provider selection is per run (`--provider`) or defaulted in config.
