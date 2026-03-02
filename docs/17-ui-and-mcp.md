# UI dashboard and MCP management

AgentForge includes a small **local web UI** that can:
- monitor workspaces + locks
- run workflows
- spawn new workspaces
- manage MCP servers via Docker MCP Toolkit (optional)

This is intended to make multi-agent operation less painful on a single machine.

---

## UI

### Read-only dashboard

```bash
agentforge serve
# open http://127.0.0.1:5179/
```

### Actions-enabled UI

```bash
agentforge ui
# prints a URL containing a token:
#   http://127.0.0.1:5179/?token=...
```

Or:

```bash
agentforge serve --actions
```

POST actions require a token via `X-AgentForge-Token`.
The UI stores it in `localStorage` if you pass it via `?token=...`.

**Security model**
- This UI is a *local convenience*, not a security boundary.
- Keep it bound to `127.0.0.1` unless you know what you’re doing.
- Treat the token like a password.

---

## MCP (Model Context Protocol) via Docker

If you already use Docker’s MCP Toolkit / `docker mcp`, AgentForge can help you:
- pick servers from the Docker catalog
- add them to a profile for this repo
- keep that profile in sync with a repo-local config file

### Repo config

`.agentforge/mcp.toml`:

```toml
backend = "docker"
catalog_ref = "mcp/docker-mcp-catalog"
profile = "agentforge"
servers = ["github-official", "playwright"]
```

### CLI

Show status:

```bash
agentforge mcp status
```

List catalog servers:

```bash
agentforge mcp catalog --filter playwright
```

Ensure profile exists and add all configured servers:

```bash
agentforge mcp sync
```

Add a single server:

```bash
agentforge mcp add --server playwright
```

### UI

The **MCP** tab lets you:
- view `.agentforge/mcp.toml`
- sync your profile (install configured servers)
- browse the catalog and add a server with one click

---

## Notes

- Docker MCP server installation may still require credentials / OAuth flows in Docker Desktop.
- AgentForge does **not** store secrets for MCP servers. Keep secrets in the MCP backend (Docker Desktop) or in your OS keychain.
