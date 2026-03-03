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

POST actions require a token via `Authorization: Bearer <token>`.
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


---

## Runs and live logs

The UI runs workflows and queue-intake jobs asynchronously and streams logs using **Server-Sent Events (SSE)**.

Key endpoints:
- `GET /api/runs?limit=20` — list recent runs
- `GET /api/run/status?run_id=...` — run metadata
- `GET /api/run/stream?run_id=...` — SSE stream of JSONL events

In the UI, the **Dashboard → Recent runs** panel shows recent run IDs and lets you stream logs into the log viewer.

Event shapes are intentionally stable:
- `workflow_start`, `step_start`, `step_end`, `workflow_end`
- `bootstrap_start`, `bootstrap_plan`, `bootstrap_item_start`, `bootstrap_item_end`, `bootstrap_end`
- `run_start`, `run_end`, `error`

---

## Queue intake (bootstrap)

The UI includes a **Queue** tab that can:
- list queue issues (`cfg.queue_label`)
- compute a bootstrap plan (auto lock-group selection)
- run bootstrap asynchronously (spawn workspaces; optionally run workflows)

Endpoints:
- `GET /api/queue/issues?limit=25`
- `GET /api/bootstrap/plan?agents=a1,a2&take=3&workflow=...`
- `POST /api/bootstrap/run_async`

---

## MCP gateway

AgentForge can optionally manage a local **Docker MCP Gateway** process.

### Configure

`.agentforge/mcp.toml`:

```toml
[gateway]
auto_start = false
inject_prompt = true
transport = "sse"
per_workspace = true
port_start = 9360
port_end = 9460
```

### UI / CLI

UI:
- **MCP → Gateway** panel can start/stop gateways.

CLI:

```bash
agentforge mcp gateway list
agentforge mcp gateway start --key a1::issue-123 --transport sse
agentforge mcp gateway stop --key a1::issue-123
```

### Runner integration

If `gateway.auto_start=true`:
- `run_agent_role()` will ensure a gateway is running
- it exports connection info via env vars (e.g. `AGENTFORGE_MCP_GATEWAY_URL`, `AGENTFORGE_MCP_GATEWAY_AUTH_TOKEN`)
- it optionally appends a short `[MCP]` hint to the agent prompt
