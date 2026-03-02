# Provider plugins

AgentForge supports external provider plugins via Python entry points.

Entry point group:
- `agentforge.providers`

Example (in your plugin package `pyproject.toml`):

```toml
[project.entry-points."agentforge.providers"]
claude = "agentforge_claude:provider"
```

Where `agentforge_claude.provider()` returns an object implementing the Provider interface:
- `.run(prompt, cwd, env) -> RunResult`

AgentForge will then accept:
```bash
agentforge run --provider claude ...
```

This lets the core project remain provider-neutral while the community adds adapters.
