from __future__ import annotations

import html
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs

from .config import RepoConfig, Policy
from .state import load_state
from .workspace import list_workspaces, spawn_workspace
from .locks import list_locks, acquire_lock, release_lock, LockTakenError
from .workflow import load_workflows, run_workflow
from .mcp import (
    load_mcp_config,
    docker_mcp_available,
    docker_catalog_server_ls,
    docker_profile_list,
    docker_profile_server_ls,
    docker_sync_profile,
    McpBackendError,
    McpConfig,
)


def _json(handler: BaseHTTPRequestHandler, code: int, payload: Dict[str, Any]) -> None:
    raw = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(raw)


def _read_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    ln = int(handler.headers.get("Content-Length") or "0")
    if ln <= 0:
        return {}
    raw = handler.rfile.read(ln)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _html(handler: BaseHTTPRequestHandler, code: int, body: str) -> None:
    raw = body.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(raw)


def serve_status(
    root: Path,
    cfg: RepoConfig,
    pol: Policy,
    state_file: Path,
    host: str = "127.0.0.1",
    port: int = 5179,
    *,
    enable_actions: bool = False,
    token: Optional[str] = None,
) -> None:
    """Serve a local dashboard UI.

    - GET endpoints are read-only.
    - If enable_actions=True, a token is required for POST endpoints.
      The token is accepted via HTTP header: X-AgentForge-Token
      (the UI stores it in localStorage).
    """
    mcp_cfg = load_mcp_config(root)
    ui_token = token
    if enable_actions and not ui_token:
        ui_token = secrets.token_urlsafe(24)

    def make_payload() -> Dict[str, Any]:
        wss = list_workspaces(state_file)
        st = load_state(state_file)
        locks = list_locks(root=root, cfg=cfg)
        payload = {
            "repo_root": str(root),
            "repo": cfg.repo,
            "workspaces": [ws.__dict__ for ws in wss],
            "ports": st.get("ports", {}),
            "locks": [li.__dict__ for li in locks],
            "policy": {
                "mode": pol.mode,
                "deny_forks": pol.deny_forks,
                "allowed_comment_authors": pol.allowed_comment_authors,
            },
        }
        return payload

    def ui_page(read_only: bool) -> str:
        # A tiny, dependency-free UI. Keep HTML static; use JS for refresh/actions.
        ro = "true" if read_only else "false"
        repo_name = html.escape(cfg.repo or "(not set)")
        root_esc = html.escape(str(root))
        return f"""<!doctype html>
<html>
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>AgentForge</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 16px; }}
header {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; flex-wrap:wrap; }}
code {{ background:#f6f8fa; padding:2px 4px; border-radius:4px; }}
small {{ color:#555; }}
.tabs button {{ margin-right:8px; }}
.panel {{ display:none; margin-top: 12px; }}
.panel.active {{ display:block; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ border:1px solid #ddd; padding:8px; text-align:left; vertical-align:top; }}
th {{ background:#f6f8fa; }}
input, select, textarea {{ width: 100%; box-sizing: border-box; padding: 6px; }}
.row {{ display:flex; gap: 12px; flex-wrap:wrap; }}
.col {{ flex: 1 1 260px; }}
.badge {{ display:inline-block; padding:2px 6px; border-radius:12px; background:#eee; font-size:12px; }}
.ok {{ background:#e6ffed; }}
.warn {{ background:#fff5b1; }}
.err {{ background:#ffeef0; }}
.actions button {{ padding:6px 10px; }}
</style>
</head>
<body>
<header>
  <div>
    <h1 style=\"margin:0\">AgentForge</h1>
    <small>Repo: <b>{repo_name}</b> · Root: <code>{root_esc}</code></small>
  </div>
  <div>
    <span class=\"badge\" id=\"mode\">mode</span>
    <span class=\"badge\" id=\"mcp\">mcp</span>
    <span class=\"badge\" id=\"ro\">{'read-only' if read_only else 'actions-enabled'}</span>
  </div>
</header>

<div class=\"tabs\" style=\"margin-top:12px\">
  <button data-tab=\"dash\">Dashboard</button>
  <button data-tab=\"workspaces\">Workspaces</button>
  <button data-tab=\"locks\">Locks</button>
  <button data-tab=\"workflows\">Workflows</button>
  <button data-tab=\"mcp\">MCP</button>
</div>

<div id=\"dash\" class=\"panel active\">
  <p>Auto-refreshes every 5s. JSON: <a href=\"/status.json\">/status.json</a></p>
  <pre id=\"summary\"></pre>
</div>

<div id=\"workspaces\" class=\"panel\">
  <div class=\"row\">
    <div class=\"col\">
      <h3>Existing workspaces</h3>
      <div id=\"ws_table\"></div>
    </div>
    <div class=\"col\">
      <h3>Spawn workspace</h3>
      <div class=\"actions\">
        <label>Agent</label><input id=\"spawn_agent\" placeholder=\"a1\">
        <label>Task</label><input id=\"spawn_task\" placeholder=\"issue-123\">
        <label>Base ref</label><input id=\"spawn_base\" placeholder=\"{html.escape(cfg.default_base_ref)}\">
        <button id=\"btn_spawn\">Spawn</button>
        <small>Spawns a git worktree + reserves a port (if configured).</small>
      </div>
    </div>
  </div>
</div>

<div id=\"locks\" class=\"panel\">
  <div class=\"row\">
    <div class=\"col\">
      <h3>Held locks</h3>
      <div id=\"lock_table\"></div>
    </div>
    <div class=\"col\">
      <h3>Acquire / release</h3>
      <div class=\"actions\">
        <label>Group</label><input id=\"lock_group\" placeholder=\"frontend\">
        <label>Agent</label><input id=\"lock_agent\" placeholder=\"a1\">
        <label>Task</label><input id=\"lock_task\" placeholder=\"issue-123\">
        <label>TTL seconds</label><input id=\"lock_ttl\" placeholder=\"14400\">
        <button id=\"btn_lock_acq\">Acquire</button>
        <button id=\"btn_lock_rel\">Release</button>
      </div>
    </div>
  </div>
</div>

<div id=\"workflows\" class=\"panel\">
  <div class=\"row\">
    <div class=\"col\">
      <h3>Run workflow</h3>
      <div class=\"actions\">
        <label>Workspace (agent:task)</label><select id=\"wf_ws\"></select>
        <label>Workflow</label><select id=\"wf_name\"></select>
        <label>Provider override (optional)</label><input id=\"wf_provider\" placeholder=\"\">
        <button id=\"btn_wf_run\">Run</button>
        <small>Runs workflow steps for the selected workspace.</small>
      </div>
      <h3>Last run output</h3>
      <pre id=\"wf_out\"></pre>
    </div>
    <div class=\"col\">
      <h3>Workflow definitions</h3>
      <pre id=\"wf_defs\"></pre>
    </div>
  </div>
</div>

<div id=\"mcp\" class=\"panel\">
  <div class=\"row\">
    <div class=\"col\">
      <h3>Config</h3>
      <pre id=\"mcp_cfg\"></pre>
      <button id=\"btn_mcp_sync\">Sync profile (install servers)</button>
      <small>Creates the configured profile (if missing) and adds servers from .agentforge/mcp.toml.</small>
    </div>
    <div class=\"col\">
      <h3>Catalog servers</h3>
      <label>Filter</label><input id=\"mcp_filter\" placeholder=\"playwright\">
      <button id=\"btn_mcp_refresh\">Refresh</button>
      <div id=\"mcp_servers\"></div>
    </div>
    <div class=\"col\">
      <h3>Profile servers</h3>
      <button id=\"btn_mcp_profile\">Refresh</button>
      <pre id=\"mcp_profile\"></pre>
    </div>
  </div>
</div>

<script>
const READ_ONLY = {ro};
function qs(sel) {{ return document.querySelector(sel); }}
function qsa(sel) {{ return Array.from(document.querySelectorAll(sel)); }}

function getToken() {{
  const u = new URL(window.location.href);
  const t = u.searchParams.get('token');
  if (t) {{
    localStorage.setItem('agentforge_token', t);
    return t;
  }}
  return localStorage.getItem('agentforge_token') || '';
}}

async function apiGet(path) {{
  const r = await fetch(path, {{cache:'no-store'}});
  return await r.json();
}}
async function apiPost(path, obj) {{
  const token = getToken();
  const r = await fetch(path, {{
    method:'POST',
    headers: {{
      'Content-Type': 'application/json',
      'X-AgentForge-Token': token,
    }},
    body: JSON.stringify(obj || {{}}),
  }});
  return await r.json();
}}

function renderTable(rows, headers) {{
  let h = '<table><tr>' + headers.map(x=>'<th>'+x+'</th>').join('') + '</tr>';
  for (const row of rows) {{
    h += '<tr>' + row.map(x=>'<td>'+x+'</td>').join('') + '</tr>';
  }}
  h += '</table>';
  return h;
}}

function setBadge(id, text, cls) {{
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = 'badge ' + cls;
}}

let lastStatus = null;

async function refreshStatus() {{
  const st = await apiGet('/api/status');
  lastStatus = st;
  setBadge('mode', 'policy: '+(st.policy?.mode||'?'), 'ok');
  setBadge('mcp', 'mcp: '+(st.mcp?.available ? 'docker-mcp ok' : 'unavailable'), st.mcp?.available ? 'ok' : 'warn');
  qs('#summary').textContent = JSON.stringify(st, null, 2);

  // workspaces
  const ws = st.workspaces || [];
  const wsRows = ws.map(w => [
    w.agent,
    w.task,
    '<code>'+w.branch+'</code>',
    '<code>'+w.path+'</code>',
    String(w.port),
  ]);
  qs('#ws_table').innerHTML = renderTable(wsRows, ['agent','task','branch','path','port']);

  // workspace selector
  const sel = qs('#wf_ws');
  sel.innerHTML = '';
  for (const w of ws) {{
    const opt = document.createElement('option');
    opt.value = w.agent+'::'+w.task;
    opt.textContent = w.agent+':'+w.task;
    sel.appendChild(opt);
  }}

  // locks
  const locks = st.locks || [];
  const lockRows = locks.map(l => [
    '<code>'+l.group+'</code>',
    l.agent,
    l.task,
    l.hostname,
    String(l.pid),
    new Date(l.created_ts*1000).toISOString(),
    (l.expires_ts ? new Date(l.expires_ts*1000).toISOString() : '(none)'),
  ]);
  qs('#lock_table').innerHTML = renderTable(lockRows, ['group','agent','task','host','pid','created','expires']);

  // workflows
  const wf = st.workflows || [];
  const wfSel = qs('#wf_name');
  wfSel.innerHTML = '';
  for (const name of wf) {{
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    wfSel.appendChild(opt);
  }}
}}

async function refreshWorkflows() {{
  const wf = await apiGet('/api/workflows');
  qs('#wf_defs').textContent = JSON.stringify(wf, null, 2);
}}

async function refreshMcpCatalog() {{
  const f = qs('#mcp_filter').value || '';
  const res = await apiGet('/api/mcp/catalog?filter='+encodeURIComponent(f));
  const ids = res.servers || [];
  const cfg = res.config || {{}};
  const prof = cfg.profile || 'agentforge';
  let html = '<table><tr><th>server id</th><th>action</th></tr>';
  for (const id of ids) {{
    html += '<tr><td><code>'+id+'</code></td><td><button data-id="'+id+'">Add to profile</button></td></tr>';
  }}
  html += '</table>';
  const box = qs('#mcp_servers');
  box.innerHTML = html;
  box.querySelectorAll('button').forEach(btn => {{
    btn.addEventListener('click', async () => {{
      if (READ_ONLY) return alert('read-only');
      const sid = btn.getAttribute('data-id');
      const r = await apiPost('/api/mcp/add', {{server_id: sid}});
      alert(JSON.stringify(r, null, 2));
    }});
  }});
}}

async function refreshMcpProfile() {{
  const res = await apiGet('/api/mcp/profile');
  qs('#mcp_profile').textContent = JSON.stringify(res, null, 2);
}}

async function refreshMcpCfg() {{
  const res = await apiGet('/api/mcp/config');
  qs('#mcp_cfg').textContent = JSON.stringify(res, null, 2);
}}

function initTabs() {{
  qsa('.tabs button').forEach(b => {{
    b.addEventListener('click', () => {{
      const tab = b.getAttribute('data-tab');
      qsa('.panel').forEach(p => p.classList.remove('active'));
      qs('#'+tab).classList.add('active');
    }});
  }});
}}

function initActions() {{
  qs('#btn_spawn').addEventListener('click', async () => {{
    if (READ_ONLY) return alert('read-only');
    const agent = qs('#spawn_agent').value.trim();
    const task = qs('#spawn_task').value.trim();
    const base_ref = qs('#spawn_base').value.trim();
    const r = await apiPost('/api/spawn', {{agent, task, base_ref}});
    alert(JSON.stringify(r, null, 2));
    await refreshStatus();
  }});

  qs('#btn_lock_acq').addEventListener('click', async () => {{
    if (READ_ONLY) return alert('read-only');
    const group = qs('#lock_group').value.trim();
    const agent = qs('#lock_agent').value.trim();
    const task = qs('#lock_task').value.trim();
    const ttl_sec = Number(qs('#lock_ttl').value.trim() || '14400');
    const r = await apiPost('/api/lock/acquire', {{group, agent, task, ttl_sec}});
    alert(JSON.stringify(r, null, 2));
    await refreshStatus();
  }});

  qs('#btn_lock_rel').addEventListener('click', async () => {{
    if (READ_ONLY) return alert('read-only');
    const group = qs('#lock_group').value.trim();
    const agent = qs('#lock_agent').value.trim();
    const task = qs('#lock_task').value.trim();
    const r = await apiPost('/api/lock/release', {{group, agent, task}});
    alert(JSON.stringify(r, null, 2));
    await refreshStatus();
  }});

  qs('#btn_wf_run').addEventListener('click', async () => {{
    if (READ_ONLY) return alert('read-only');
    const ws = qs('#wf_ws').value;
    const [agent, task] = ws.split('::');
    const workflow = qs('#wf_name').value;
    const provider = qs('#wf_provider').value.trim();
    const r = await apiPost('/api/workflow/run', {{agent, task, workflow, provider}});
    qs('#wf_out').textContent = JSON.stringify(r, null, 2);
    await refreshStatus();
  }});

  qs('#btn_mcp_refresh').addEventListener('click', async () => {{
    await refreshMcpCatalog();
  }});
  qs('#btn_mcp_profile').addEventListener('click', async () => {{
    await refreshMcpProfile();
  }});
  qs('#btn_mcp_sync').addEventListener('click', async () => {{
    if (READ_ONLY) return alert('read-only');
    const r = await apiPost('/api/mcp/sync', {{}});
    alert(JSON.stringify(r, null, 2));
    await refreshMcpCfg();
    await refreshMcpProfile();
  }});
}}

async function main() {{
  initTabs();
  initActions();
  await refreshMcpCfg();
  await refreshWorkflows();
  await refreshStatus();
  setInterval(refreshStatus, 5000);
}}
main();
</script>
</body>
</html>"""

    class Handler(BaseHTTPRequestHandler):
        def _auth_ok(self) -> bool:
            if not enable_actions:
                return False
            req = self.headers.get("X-AgentForge-Token") or ""
            return bool(ui_token) and secrets.compare_digest(req, ui_token)

        def do_OPTIONS(self):  # noqa: N802
            # Minimal CORS handling for local UI; keep strict.
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-AgentForge-Token")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            path = u.path
            qs_params = parse_qs(u.query)

            if path in ["/", "/status", "/ui"]:
                _html(self, 200, ui_page(read_only=not enable_actions))
                return

            if path in ["/status.json", "/api/status"]:
                payload = make_payload()
                # attach UI+MCP info
                payload["ui"] = {"actions_enabled": bool(enable_actions)}
                payload["mcp"] = {"available": docker_mcp_available(), "profile": mcp_cfg.profile, "catalog_ref": mcp_cfg.catalog_ref}
                payload["workflows"] = sorted(load_workflows(root).keys())
                _json(self, 200, payload)
                return

            if path == "/api/workflows":
                _json(self, 200, {"workflows": load_workflows(root)})
                return

            if path == "/api/locks":
                locks = list_locks(root=root, cfg=cfg)
                _json(self, 200, {"locks": [li.__dict__ for li in locks]})
                return

            if path == "/api/mcp/config":
                _json(
                    self,
                    200,
                    {
                        "available": docker_mcp_available(),
                        "config": {
                            "backend": mcp_cfg.backend,
                            "catalog_ref": mcp_cfg.catalog_ref,
                            "profile": mcp_cfg.profile,
                            "servers": list(mcp_cfg.servers or []),
                        },
                    },
                )
                return

            if path == "/api/mcp/catalog":
                filt = (qs_params.get("filter") or [""])[0].strip().lower()
                if not docker_mcp_available():
                    _json(self, 200, {"ok": False, "error": "docker mcp not available", "servers": [], "config": mcp_cfg.__dict__})
                    return
                servers = docker_catalog_server_ls(mcp_cfg.catalog_ref)
                if filt:
                    servers = [s for s in servers if filt in s.lower()]
                _json(self, 200, {"ok": True, "servers": servers[:200], "config": mcp_cfg.__dict__})
                return

            if path == "/api/mcp/profile":
                if not docker_mcp_available():
                    _json(self, 200, {"ok": False, "error": "docker mcp not available"})
                    return
                profiles = docker_profile_list()
                profile_servers = docker_profile_server_ls(mcp_cfg.profile) if mcp_cfg.profile else ""
                _json(self, 200, {"ok": True, "profiles": profiles, "profile": mcp_cfg.profile, "servers": profile_servers})
                return

            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

        def do_POST(self):  # noqa: N802
            u = urlparse(self.path)
            path = u.path

            if not enable_actions:
                _json(self, 403, {"ok": False, "error": "actions disabled"})
                return
            if not self._auth_ok():
                _json(self, 401, {"ok": False, "error": "bad token"})
                return

            data = _read_json(self)

            try:
                if path == "/api/spawn":
                    agent = str(data.get("agent") or "").strip()
                    task = str(data.get("task") or "").strip()
                    base_ref = str(data.get("base_ref") or cfg.default_base_ref).strip()
                    if not agent or not task:
                        _json(self, 400, {"ok": False, "error": "agent and task required"})
                        return
                    st = load_state(state_file)
                    ws = spawn_workspace(root, cfg, pol, state_file, agent=agent, task=task, base_ref=base_ref)
                    _json(self, 200, {"ok": True, "workspace": ws.__dict__})
                    return

                if path == "/api/lock/acquire":
                    group = str(data.get("group") or "").strip()
                    agent = str(data.get("agent") or "").strip()
                    task = str(data.get("task") or "").strip()
                    ttl = int(data.get("ttl_sec") or 6 * 60 * 60)
                    if not group or not agent or not task:
                        _json(self, 400, {"ok": False, "error": "group/agent/task required"})
                        return
                    info = acquire_lock(root=root, cfg=cfg, group=group, agent=agent, task=task, ttl_sec=ttl, force=False)
                    _json(self, 200, {"ok": True, "lock": info.__dict__})
                    return

                if path == "/api/lock/release":
                    group = str(data.get("group") or "").strip()
                    agent = str(data.get("agent") or "").strip()
                    task = str(data.get("task") or "").strip()
                    if not group:
                        _json(self, 400, {"ok": False, "error": "group required"})
                        return
                    release_lock(root=root, cfg=cfg, group=group, agent=agent or None, task=task or None, force=False)
                    _json(self, 200, {"ok": True})
                    return

                if path == "/api/workflow/run":
                    agent = str(data.get("agent") or "").strip()
                    task = str(data.get("task") or "").strip()
                    workflow = str(data.get("workflow") or "").strip()
                    provider = str(data.get("provider") or "").strip() or None
                    if not agent or not task or not workflow:
                        _json(self, 400, {"ok": False, "error": "agent/task/workflow required"})
                        return
                    summary = run_workflow(
                        root=root,
                        cfg=cfg,
                        pol=pol,
                        agent=agent,
                        task=task,
                        workflow=workflow,
                        provider_default=provider or cfg.default_provider,
                        extra_ctx=None,
                        dry_run=False,
                        log_json=True,
                    )
                    _json(self, 200, {"ok": True, "summary": summary.__dict__})
                    return

                if path == "/api/mcp/sync":
                    if not docker_mcp_available():
                        _json(self, 400, {"ok": False, "error": "docker mcp not available"})
                        return
                    docker_sync_profile(mcp_cfg)
                    _json(self, 200, {"ok": True, "profile": mcp_cfg.profile, "servers": list(mcp_cfg.servers or [])})
                    return

                if path == "/api/mcp/add":
                    if not docker_mcp_available():
                        _json(self, 400, {"ok": False, "error": "docker mcp not available"})
                        return
                    sid = str(data.get("server_id") or "").strip()
                    if not sid:
                        _json(self, 400, {"ok": False, "error": "server_id required"})
                        return
                    # Add just that server to the configured profile
                    docker_sync_profile(McpConfig(backend=mcp_cfg.backend, catalog_ref=mcp_cfg.catalog_ref, profile=mcp_cfg.profile, servers=[sid]))
                    _json(self, 200, {"ok": True, "added": sid, "profile": mcp_cfg.profile})
                    return

                _json(self, 404, {"ok": False, "error": "unknown endpoint"})
                return

            except LockTakenError as e:
                _json(self, 409, {"ok": False, "error": str(e), "holder": e.holder.__dict__})
                return
            except McpBackendError as e:
                _json(self, 400, {"ok": False, "error": str(e)})
                return
            except Exception as e:
                _json(self, 500, {"ok": False, "error": str(e)})
                return

        def log_message(self, format, *args):  # noqa: A003
            # Quiet
            return

    httpd = HTTPServer((host, port), Handler)
    if enable_actions:
        print(f"AgentForge UI (actions enabled): http://{host}:{port}/?token={ui_token}")
        print("Token is required for POST actions (header X-AgentForge-Token). Keep it local.")
    else:
        print(f"AgentForge dashboard: http://{host}:{port}/")
    httpd.serve_forever()
