from __future__ import annotations

import html
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs

from .config import RepoConfig, Policy
from .state import load_state
from .workspace import list_workspaces, spawn_workspace
from .locks import list_locks, acquire_lock, release_lock
from .workflow import load_workflows, run_workflow
from .bootstrap import run_bootstrap, build_plan_from_queue
from .queue import list_issues
from .mcp import (
    load_mcp_config,
    docker_mcp_available,
    docker_mcp_version,
    docker_catalog_server_ls,
    docker_profile_list,
    docker_profile_server_ls,
    docker_sync_profile,
    docker_profile_server_add,
    docker_profile_server_remove,
    ensure_gateway_running,
    list_gateways,
    stop_gateway,
)
from .runs import create_run, append_event, update_run_meta, list_runs, read_run_meta


def _now() -> int:
    return int(time.time())


def _json(handler: BaseHTTPRequestHandler, code: int, obj: Any) -> None:
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _text(handler: BaseHTTPRequestHandler, code: int, text: str, *, ctype: str = "text/plain; charset=utf-8") -> None:
    raw = text.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _unauthorized(handler: BaseHTTPRequestHandler) -> None:
    _json(handler, 401, {"ok": False, "error": "unauthorized"})


def serve_status(
    root: Path,
    cfg: RepoConfig,
    pol: Policy,
    st_file: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    enable_actions: bool = False,
    token: Optional[str] = None,
) -> None:
    """Serve a small local UI + JSON API for AgentForge.

    - bind defaults to localhost (127.0.0.1)
    - when enable_actions=True, POST endpoints require Authorization: Bearer <token>
    - SSE (/api/run/stream) is read-only and does not require auth; run_id is unguessable
    """
    token = token or secrets.token_hex(16)

    def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
        if not enable_actions:
            return True
        auth = handler.headers.get("Authorization") or ""
        want = f"Bearer {token}"
        return secrets.compare_digest(auth.strip(), want)

    def _html_page() -> str:
        # Minimal dependency-free UI. (Edit carefully; shipped as a python string.)
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AgentForge UI</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; }}
header {{ display: flex; gap: 12px; align-items: center; padding: 12px 16px; border-bottom: 1px solid #ddd; background: #fafafa; position: sticky; top: 0; }}
header h1 {{ font-size: 16px; margin: 0; }}
nav {{ display: flex; gap: 8px; flex-wrap: wrap; }}
nav button {{ padding: 6px 10px; border: 1px solid #ccc; border-radius: 8px; background: #fff; cursor: pointer; }}
nav button.active {{ background: #eef; border-color: #99f; }}
main {{ padding: 16px; }}
.card {{ border: 1px solid #ddd; border-radius: 12px; padding: 12px; margin: 10px 0; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
label {{ display: block; font-size: 12px; color: #444; margin-bottom: 4px; }}
input, textarea, select {{ width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 10px; }}
textarea {{ min-height: 90px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }}
pre {{ background: #0b1020; color: #d7e3ff; padding: 12px; border-radius: 12px; overflow: auto; }}
.row {{ display:flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }}
.row > div {{ flex: 1; min-width: 240px; }}
small.muted {{ color: #666; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eee; font-size: 12px; }}
.badge.ok {{ background: #e6ffed; border: 1px solid #8ddf9b; }}
.badge.fail {{ background: #ffe6e6; border: 1px solid #e0a0a0; }}
table {{ width:100%; border-collapse: collapse; }}
th, td {{ text-align:left; padding: 6px 8px; border-bottom: 1px solid #eee; font-size: 13px; }}
.tab {{ display: none; }}
.tab.active {{ display: block; }}
button.primary {{ background: #1d4ed8; border-color: #1d4ed8; color: white; }}
button.danger {{ background: #b91c1c; border-color: #b91c1c; color: white; }}
</style>
</head>
<body>
<header>
  <h1>AgentForge UI</h1>
  <nav>
    <button id="tabbtn-dashboard" onclick="showTab('dashboard')" class="active">Dashboard</button>
    <button id="tabbtn-workspaces" onclick="showTab('workspaces')">Workspaces</button>
    <button id="tabbtn-locks" onclick="showTab('locks')">Locks</button>
    <button id="tabbtn-workflows" onclick="showTab('workflows')">Workflows</button>
    <button id="tabbtn-queue" onclick="showTab('queue')">Queue</button>
    <button id="tabbtn-mcp" onclick="showTab('mcp')">MCP</button>
  </nav>
  <div style="margin-left:auto">
    <span class="badge" id="actionsBadge">actions: {('enabled' if enable_actions else 'disabled')}</span>
  </div>
</header>
<main>
  <section id="dashboard" class="tab active">
    <div class="grid">
      <div class="card">
        <h3 style="margin-top:0">Repo</h3>
        <div><b>Root:</b> <span id="repoRoot"></span></div>
        <div><b>Configured repo:</b> <span id="repoName"></span></div>
        <div><b>Default provider:</b> <span id="defProv"></span></div>
        <div><b>Default workflow:</b> <span id="defWf"></span></div>
      </div>
      <div class="card">
        <h3 style="margin-top:0">System</h3>
        <div><b>Workspaces:</b> <span id="wsCount"></span></div>
        <div><b>Locks:</b> <span id="lockCount"></span></div>
        <div><b>MCP backend:</b> <span id="mcpAvail"></span></div>
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Recent runs</h3>
      <small class="muted">Workflow/bootstrap runs started from the UI are logged to .agentforge/logs/runs/ and streamed live via SSE.</small>
      <div style="margin-top:8px">
        <button onclick="refreshRuns()">Refresh runs</button>
      </div>
      <div id="runsTableWrap" style="margin-top:8px"></div>
      <h4>Run log</h4>
      <pre id="runLog">(select a run)</pre>
    </div>
  </section>

  <section id="workspaces" class="tab">
    <div class="card">
      <h3 style="margin-top:0">Spawn workspace</h3>
      <div class="row">
        <div>
          <label>Agent</label>
          <input id="spawnAgent" placeholder="a1"/>
        </div>
        <div>
          <label>Task</label>
          <input id="spawnTask" placeholder="issue-123"/>
        </div>
        <div>
          <label>Base ref</label>
          <input id="spawnBase" placeholder="origin/main"/>
        </div>
        <div style="flex:0">
          <button class="primary" onclick="spawnWs()">Spawn</button>
        </div>
      </div>
      <small class="muted">Uses git worktrees under {html.escape(cfg.worktrees_dir)}.</small>
      <pre id="spawnOut"></pre>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Workspaces</h3>
      <div id="wsTableWrap"></div>
    </div>
  </section>

  <section id="locks" class="tab">
    <div class="card">
      <h3 style="margin-top:0">Locks</h3>
      <div id="locksTableWrap"></div>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Acquire / release lock</h3>
      <div class="row">
        <div><label>Group</label><input id="lockGroup" placeholder="frontend"/></div>
        <div><label>Agent</label><input id="lockAgent" placeholder="a1"/></div>
        <div><label>Task</label><input id="lockTask" placeholder="issue-123"/></div>
        <div><label>TTL (sec)</label><input id="lockTtl" placeholder="21600"/></div>
      </div>
      <div class="row" style="margin-top:8px">
        <div style="flex:0"><button class="primary" onclick="lockAcquire()">Acquire</button></div>
        <div style="flex:0"><button class="danger" onclick="lockRelease()">Release</button></div>
      </div>
      <pre id="lockOut"></pre>
    </div>
  </section>

  <section id="workflows" class="tab">
    <div class="card">
      <h3 style="margin-top:0">Run workflow</h3>
      <div class="row">
        <div><label>Agent</label><input id="wfAgent" placeholder="a1"/></div>
        <div><label>Task</label><input id="wfTask" placeholder="issue-123"/></div>
        <div>
          <label>Workflow</label>
          <select id="wfName"></select>
        </div>
        <div style="flex:0">
          <button class="primary" onclick="runWorkflowAsync()">Run</button>
        </div>
      </div>
      <small class="muted">Runs asynchronously and streams step logs live.</small>
      <pre id="wfOut"></pre>
    </div>
  </section>

  <section id="queue" class="tab">
    <div class="card">
      <h3 style="margin-top:0">Queue intake (bootstrap)</h3>
      <small class="muted">Takes issues from the GitHub queue label ({html.escape(cfg.queue_label)}) and spawns workspaces. Optionally runs workflows immediately.</small>
      <div class="row" style="margin-top:8px">
        <div>
          <label>Agents (comma separated)</label>
          <input id="qAgents" placeholder="a1,a2,a3"/>
        </div>
        <div>
          <label>Take</label>
          <input id="qTake" placeholder="3"/>
        </div>
        <div>
          <label>Workflow override (optional)</label>
          <input id="qWfOverride" placeholder=""/>
        </div>
      </div>
      <div class="row" style="margin-top:8px">
        <div>
          <label><input type="checkbox" id="qFast" checked/> Run workflows (fast mode)</label>
          <label><input type="checkbox" id="qClaim"/> Claim issues (move labels)</label>
          <label><input type="checkbox" id="qCreatePR" checked/> Create PRs (if workflow includes pr step)</label>
          <label><input type="checkbox" id="qDraftPR" checked/> Draft PRs</label>
        </div>
        <div style="flex:0">
          <button onclick="previewPlan()">Preview plan</button>
        </div>
        <div style="flex:0">
          <button class="primary" onclick="runBootstrapAsync()">Run bootstrap</button>
        </div>
      </div>
      <h4>Plan</h4>
      <pre id="qPlan">(click Preview plan)</pre>
      <h4>Logs</h4>
      <pre id="qOut"></pre>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Queue issues</h3>
      <div style="margin-top:8px"><button onclick="refreshQueue()">Refresh issues</button></div>
      <div id="queueTableWrap" style="margin-top:8px"></div>
    </div>
  </section>

  <section id="mcp" class="tab">
    <div class="card">
      <h3 style="margin-top:0">MCP status</h3>
      <div><b>docker mcp available:</b> <span id="mcpOk"></span></div>
      <div><b>docker mcp version:</b> <span id="mcpVer"></span></div>
      <div><b>profile:</b> <span id="mcpProfile"></span></div>
      <div><b>catalog:</b> <span id="mcpCatalog"></span></div>
      <div style="margin-top:8px">
        <button onclick="mcpSync()">Sync profile</button>
      </div>
      <pre id="mcpStatusOut"></pre>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Catalog servers</h3>
      <div class="row">
        <div><label>Filter</label><input id="mcpFilter" placeholder="github"/></div>
        <div style="flex:0"><button onclick="mcpCatalog()">List</button></div>
      </div>
      <pre id="mcpCatalogOut"></pre>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Profile servers</h3>
      <div class="row">
        <div style="flex:0"><button onclick="mcpProfile()">Refresh</button></div>
      </div>
      <pre id="mcpProfileOut"></pre>

      <div class="row" style="margin-top:8px">
        <div><label>Add server by ID</label><input id="mcpAddId" placeholder="playwright"/></div>
        <div style="flex:0"><button class="primary" onclick="mcpAdd()">Add</button></div>
      </div>

      <div class="row" style="margin-top:8px">
        <div><label>Remove server by name</label><input id="mcpRemoveName" placeholder="playwright"/></div>
        <div style="flex:0"><button class="danger" onclick="mcpRemove()">Remove</button></div>
      </div>
      <pre id="mcpEditOut"></pre>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Gateway</h3>
      <small class="muted">Optional: run Docker MCP Gateway (SSE/streaming transport). For most users of Docker Desktop MCP Toolkit, the Gateway runs automatically.</small>
      <div style="margin-top:8px">
        <button onclick="mcpGatewayList()">Refresh gateways</button>
      </div>
      <div id="gwTableWrap" style="margin-top:8px"></div>
      <div class="row" style="margin-top:8px">
        <div><label>Scope key (optional)</label><input id="gwKey" placeholder="a1::issue-123 (blank = repo/global)"/></div>
        <div><label>Transport</label><select id="gwTransport"><option value="">(default)</option><option>sse</option><option>streaming</option></select></div>
        <div style="flex:0"><button class="primary" onclick="mcpGatewayStart()">Start</button></div>
        <div style="flex:0"><button class="danger" onclick="mcpGatewayStop()">Stop</button></div>
      </div>
      <pre id="gwOut"></pre>
    </div>
  </section>

</main>

<script>
const TOKEN = {json.dumps(token)};
const ACTIONS_ENABLED = {json.dumps(bool(enable_actions))};

function showTab(name) {{
  for (const sec of document.querySelectorAll('.tab')) {{
    sec.classList.remove('active');
  }}
  for (const btn of document.querySelectorAll('nav button')) {{
    btn.classList.remove('active');
  }}
  document.getElementById(name).classList.add('active');
  document.getElementById('tabbtn-' + name).classList.add('active');
}}

async function apiGet(path) {{
  const r = await fetch(path, {{headers: {{}}}});
  const t = await r.text();
  try {{ return {{ok: r.ok, status: r.status, data: JSON.parse(t)}}; }}
  catch (e) {{ return {{ok: r.ok, status: r.status, data: t}}; }}
}}

async function apiPost(path, body) {{
  const headers = {{
    'Content-Type': 'application/json'
  }};
  if (ACTIONS_ENABLED) {{
    headers['Authorization'] = 'Bearer ' + TOKEN;
  }}
  const r = await fetch(path, {{
    method: 'POST',
    headers,
    body: JSON.stringify(body || {{}})
  }});
  const t = await r.text();
  try {{ return {{ok: r.ok, status: r.status, data: JSON.parse(t)}}; }}
  catch (e) {{ return {{ok: r.ok, status: r.status, data: t}}; }}
}}

function fmtEvent(ev) {{
  // Make streaming logs human-readable.
  const ts = ev.ts ? new Date(ev.ts*1000).toISOString() : '';
  const kind = ev.type || 'event';
  if (kind === 'step_end') {{
    return `${{ts}} [${{ev.step_type}}] ${{ev.ok ? 'OK' : 'FAIL'}} ${{ev.message||''}}`;
  }}
  if (kind === 'step_start') {{
    return `${{ts}} -> step_start [${{ev.step_type}}]`;
  }}
  if (kind === 'workflow_start') {{
    return `${{ts}} workflow_start ${{ev.workflow}} (${{ev.agent}}:${{ev.task}})`;
  }}
  if (kind === 'workflow_end') {{
    return `${{ts}} workflow_end ${{ev.workflow}} pr=${{ev.pr_url||''}}`;
  }}
  if (kind === 'bootstrap_start') {{
    return `${{ts}} bootstrap_start take=${{ev.take}} agents=${{(ev.agents||[]).join(',')}}`;
  }}
  if (kind === 'bootstrap_plan') {{
    return `${{ts}} bootstrap_plan items=${{(ev.items||[]).length}}`;
  }}
  if (kind === 'bootstrap_item_start') {{
    return `${{ts}} bootstrap_item_start ${{ev.agent}}:${{ev.task}} #${{ev.issue_number}} lock=${{ev.lock_group}} wf=${{ev.workflow}}`;
  }}
  if (kind === 'bootstrap_item_end') {{
    return `${{ts}} bootstrap_item_end ${{ev.agent}}:${{ev.task}} ok=${{ev.ok}} pr=${{ev.pr_url||''}}`;
  }}
  if (kind === 'error') {{
    return `${{ts}} ERROR ${{ev.error||ev.message||''}}`;
  }}
  return `${{ts}} ${{kind}} ${{ev.message ? ev.message : ''}}`.trim();
}}

function startRunStream(run_id, outEl) {{
  outEl.textContent = '';
  const es = new EventSource(`/api/run/stream?run_id=${{encodeURIComponent(run_id)}}`);
  es.onmessage = (msg) => {{
    try {{
      const ev = JSON.parse(msg.data);
      outEl.textContent += fmtEvent(ev) + "\\n";
    }} catch (e) {{
      outEl.textContent += msg.data + "\\n";
    }}
    outEl.scrollTop = outEl.scrollHeight;
  }};
  es.onerror = () => {{
    // Browser will retry automatically; once server closes, this will fire.
    // We close to avoid infinite retries on finished runs.
    es.close();
  }};
  return es;
}}

let currentRunES = null;
function viewRun(run_id) {{
  if (currentRunES) {{
    currentRunES.close();
    currentRunES = null;
  }}
  const outEl = document.getElementById('runLog');
  outEl.textContent = '(streaming...)';
  currentRunES = startRunStream(run_id, outEl);
}}

async function refreshRuns() {{
  const wrap = document.getElementById('runsTableWrap');
  const r = await apiGet('/api/runs?limit=20');
  if (!r.ok) {{
    wrap.innerHTML = '<pre>' + htmlEscape(JSON.stringify(r.data, null, 2)) + '</pre>';
    return;
  }}
  const rows = (r.data.runs || []).map(x => {{
    const st = x.status || 'unknown';
    const badge = st === 'finished' ? 'ok' : (st === 'failed' ? 'fail' : '');
    const started = x.started_ts ? new Date(x.started_ts*1000).toLocaleString() : '';
    const title = x.title || x.kind || x.run_id;
    return `<tr>
      <td><span class="badge ${{badge}}">${{htmlEscape(st)}}</span></td>
      <td>${{htmlEscape(started)}}</td>
      <td>${{htmlEscape(title)}}</td>
      <td><code>${{htmlEscape(x.run_id)}}</code></td>
      <td><button onclick="viewRun('${{htmlEscape(x.run_id)}}')">View</button></td>
    </tr>`;
  }}).join('');
  wrap.innerHTML = `<table>
    <thead><tr><th>Status</th><th>Started</th><th>Title</th><th>ID</th><th></th></tr></thead>
    <tbody>${{rows || '<tr><td colspan="5"><i>(none)</i></td></tr>'}}</tbody>
  </table>`;
}}

function htmlEscape(s) {{
  return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
}}

async function refresh() {{
  const r = await apiGet('/api/status');
  if (!r.ok) {{
    alert('Failed to fetch status: ' + JSON.stringify(r.data));
    return;
  }}
  const st = r.data;
  document.getElementById('repoRoot').textContent = st.root;
  document.getElementById('repoName').textContent = st.repo || '(not set)';
  document.getElementById('defProv').textContent = st.default_provider;
  document.getElementById('defWf').textContent = st.default_workflow;
  document.getElementById('wsCount').textContent = String((st.workspaces||[]).length);
  document.getElementById('lockCount').textContent = String((st.locks||[]).length);
  document.getElementById('mcpAvail').textContent = st.mcp && st.mcp.available ? 'available' : 'not available';
  // workflows dropdown
  const sel = document.getElementById('wfName');
  sel.innerHTML = '';
  for (const w of (st.workflows||[])) {{
    const opt = document.createElement('option');
    opt.textContent = w;
    opt.value = w;
    sel.appendChild(opt);
  }}
  // workspaces table
  renderWorkspaces(st.workspaces||[]);
  renderLocks(st.locks||[]);
  // MCP
  document.getElementById('mcpOk').textContent = String(st.mcp && st.mcp.available);
  document.getElementById('mcpProfile').textContent = st.mcp ? st.mcp.profile : '';
  document.getElementById('mcpCatalog').textContent = st.mcp ? st.mcp.catalog_ref : '';
  const ver = await apiGet('/api/mcp/version');
  document.getElementById('mcpVer').textContent = ver.ok ? (ver.data.version || '') : '';
  await refreshRuns();
}}

function renderWorkspaces(items) {{
  const wrap = document.getElementById('wsTableWrap');
  if (!items.length) {{
    wrap.innerHTML = '<i>(none)</i>';
    return;
  }}
  const rows = items.map(ws => `<tr>
    <td><code>${{htmlEscape(ws.agent)}}</code></td>
    <td><code>${{htmlEscape(ws.task)}}</code></td>
    <td><code>${{htmlEscape(ws.branch)}}</code></td>
    <td><code>${{htmlEscape(ws.path)}}</code></td>
  </tr>`).join('');
  wrap.innerHTML = `<table>
    <thead><tr><th>Agent</th><th>Task</th><th>Branch</th><th>Path</th></tr></thead>
    <tbody>${{rows}}</tbody>
  </table>`;
}}

function renderLocks(items) {{
  const wrap = document.getElementById('locksTableWrap');
  if (!items.length) {{
    wrap.innerHTML = '<i>(none)</i>';
    return;
  }}
  const rows = items.map(l => {{
    const exp = l.expires_ts ? new Date(l.expires_ts*1000).toLocaleString() : '';
    return `<tr>
      <td><code>${{htmlEscape(l.group)}}</code></td>
      <td>${{htmlEscape(l.agent)}}:${{htmlEscape(l.task)}}</td>
      <td>${{htmlEscape(l.hostname||'')}}</td>
      <td>${{htmlEscape(exp)}}</td>
      <td>${{l.sticky ? '<span class="badge">sticky</span>' : ''}}</td>
      <td>${{l.pr_number ? ('#' + l.pr_number) : ''}}</td>
    </tr>`;
  }}).join('');
  wrap.innerHTML = `<table>
    <thead><tr><th>Group</th><th>Owner</th><th>Host</th><th>Expires</th><th></th><th>PR</th></tr></thead>
    <tbody>${{rows}}</tbody>
  </table>`;
}}

async function spawnWs() {{
  const out = document.getElementById('spawnOut');
  const agent = document.getElementById('spawnAgent').value.trim();
  const task = document.getElementById('spawnTask').value.trim();
  const base = document.getElementById('spawnBase').value.trim() || 'origin/main';
  const r = await apiPost('/api/workspaces/spawn', {{agent, task, base_ref: base}});
  out.textContent = JSON.stringify(r.data, null, 2);
  await refresh();
}}

async function lockAcquire() {{
  const out = document.getElementById('lockOut');
  const group = document.getElementById('lockGroup').value.trim();
  const agent = document.getElementById('lockAgent').value.trim();
  const task = document.getElementById('lockTask').value.trim();
  const ttl = parseInt(document.getElementById('lockTtl').value.trim() || '21600', 10);
  const r = await apiPost('/api/locks/acquire', {{group, agent, task, ttl_sec: ttl}});
  out.textContent = JSON.stringify(r.data, null, 2);
  await refresh();
}}

async function lockRelease() {{
  const out = document.getElementById('lockOut');
  const group = document.getElementById('lockGroup').value.trim();
  const agent = document.getElementById('lockAgent').value.trim();
  const task = document.getElementById('lockTask').value.trim();
  const r = await apiPost('/api/locks/release', {{group, agent, task}});
  out.textContent = JSON.stringify(r.data, null, 2);
  await refresh();
}}

let wfES = null;
async function runWorkflowAsync() {{
  const out = document.getElementById('wfOut');
  if (wfES) {{ wfES.close(); wfES = null; }}
  const agent = document.getElementById('wfAgent').value.trim();
  const task = document.getElementById('wfTask').value.trim();
  const workflow = document.getElementById('wfName').value;
  const r = await apiPost('/api/workflow/run_async', {{agent, task, workflow}});
  if (!r.ok) {{
    out.textContent = JSON.stringify(r.data, null, 2);
    return;
  }}
  out.textContent = 'run_id: ' + r.data.run_id + "\\n";
  wfES = startRunStream(r.data.run_id, out);
  await refreshRuns();
}}

let qES = null;
async function previewPlan() {{
  const out = document.getElementById('qPlan');
  const agentsRaw = document.getElementById('qAgents').value.trim();
  const take = parseInt(document.getElementById('qTake').value.trim() || '3', 10);
  const wf = document.getElementById('qWfOverride').value.trim();
  const r = await apiGet('/api/bootstrap/plan?agents=' + encodeURIComponent(agentsRaw) + '&take=' + take + '&workflow=' + encodeURIComponent(wf));
  out.textContent = JSON.stringify(r.data, null, 2);
}}

async function runBootstrapAsync() {{
  const out = document.getElementById('qOut');
  if (qES) {{ qES.close(); qES = null; }}
  const agents = (document.getElementById('qAgents').value || '').split(',').map(s => s.trim()).filter(Boolean);
  const take = parseInt(document.getElementById('qTake').value.trim() || '3', 10);
  const workflow_override = document.getElementById('qWfOverride').value.trim() || null;
  const fast = document.getElementById('qFast').checked;
  const claim = document.getElementById('qClaim').checked;
  const create_prs = document.getElementById('qCreatePR').checked;
  const draft_prs = document.getElementById('qDraftPR').checked;

  const r = await apiPost('/api/bootstrap/run_async', {{agents, take, fast, claim, create_prs, draft_prs, workflow_override}});
  if (!r.ok) {{
    out.textContent = JSON.stringify(r.data, null, 2);
    return;
  }}
  out.textContent = 'run_id: ' + r.data.run_id + "\\n";
  qES = startRunStream(r.data.run_id, out);
  await refresh();
}}

async function refreshQueue() {{
  const wrap = document.getElementById('queueTableWrap');
  const r = await apiGet('/api/queue/issues?limit=25');
  if (!r.ok) {{
    wrap.innerHTML = '<pre>' + htmlEscape(JSON.stringify(r.data, null, 2)) + '</pre>';
    return;
  }}
  const items = r.data.issues || [];
  const rows = items.map(it => `<tr>
    <td>#${{it.number}}</td>
    <td>${{htmlEscape(it.title)}}</td>
    <td>${{htmlEscape((it.labels||[]).join(', '))}}</td>
    <td><a href="${{htmlEscape(it.url)}}" target="_blank">link</a></td>
  </tr>`).join('');
  wrap.innerHTML = `<table><thead><tr><th>Issue</th><th>Title</th><th>Labels</th><th></th></tr></thead><tbody>${{rows || '<tr><td colspan="4"><i>(none)</i></td></tr>'}}</tbody></table>`;
}}

async function mcpSync() {{
  const out = document.getElementById('mcpStatusOut');
  const r = await apiPost('/api/mcp/sync', {{}});
  out.textContent = JSON.stringify(r.data, null, 2);
  await refresh();
}}

async function mcpCatalog() {{
  const out = document.getElementById('mcpCatalogOut');
  const filter = document.getElementById('mcpFilter').value.trim() || null;
  const r = await apiGet('/api/mcp/catalog?filter=' + encodeURIComponent(filter || ''));
  out.textContent = JSON.stringify(r.data, null, 2);
}}

async function mcpProfile() {{
  const out = document.getElementById('mcpProfileOut');
  const r = await apiGet('/api/mcp/profile');
  out.textContent = JSON.stringify(r.data, null, 2);
}}

async function mcpAdd() {{
  const out = document.getElementById('mcpEditOut');
  const server = document.getElementById('mcpAddId').value.trim();
  const r = await apiPost('/api/mcp/profile/add', {{server}});
  out.textContent = JSON.stringify(r.data, null, 2);
  await mcpProfile();
}}

async function mcpRemove() {{
  const out = document.getElementById('mcpEditOut');
  const name = document.getElementById('mcpRemoveName').value.trim();
  const r = await apiPost('/api/mcp/profile/remove', {{name}});
  out.textContent = JSON.stringify(r.data, null, 2);
  await mcpProfile();
}}

async function mcpGatewayList() {{
  const wrap = document.getElementById('gwTableWrap');
  const r = await apiGet('/api/mcp/gateway/list');
  if (!r.ok) {{
    wrap.innerHTML = '<pre>' + htmlEscape(JSON.stringify(r.data, null, 2)) + '</pre>';
    return;
  }}
  const gws = r.data.gateways || [];
  const rows = gws.map(g => `<tr>
    <td><code>${{htmlEscape(g.key || '')}}</code></td>
    <td>${{htmlEscape(g.profile || '')}}</td>
    <td>${{htmlEscape(g.transport || '')}}</td>
    <td>${{htmlEscape(g.url || '')}}</td>
    <td><code>${{htmlEscape(String(g.pid||''))}}</code></td>
  </tr>`).join('');
  wrap.innerHTML = `<table><thead><tr><th>Key</th><th>Profile</th><th>Transport</th><th>URL</th><th>PID</th></tr></thead><tbody>${{rows || '<tr><td colspan="5"><i>(none)</i></td></tr>'}}</tbody></table>`;
}}

async function mcpGatewayStart() {{
  const out = document.getElementById('gwOut');
  const key = document.getElementById('gwKey').value.trim() || null;
  const transport = document.getElementById('gwTransport').value.trim() || null;
  const r = await apiPost('/api/mcp/gateway/start', {{key, transport}});
  out.textContent = JSON.stringify(r.data, null, 2);
  await mcpGatewayList();
}}

async function mcpGatewayStop() {{
  const out = document.getElementById('gwOut');
  const key = document.getElementById('gwKey').value.trim() || null;
  const r = await apiPost('/api/mcp/gateway/stop', {{key}});
  out.textContent = JSON.stringify(r.data, null, 2);
  await mcpGatewayList();
}}

refresh();
</script>
</body>
</html>"""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            # Keep server quiet by default; comment out for debugging.
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query or "")

            if path == "/":
                _text(self, 200, _html_page(), ctype="text/html; charset=utf-8")
                return

            # ----- Runs + SSE -----
            if path == "/api/runs":
                limit = int((qs.get("limit") or ["20"])[0])
                _json(self, 200, {"ok": True, "runs": list_runs(root, cfg, limit=limit)})
                return

            if path == "/api/run/status":
                run_id = (qs.get("run_id") or [""])[0].strip()
                meta = read_run_meta(root, cfg, run_id)
                if not meta:
                    _json(self, 404, {"ok": False, "error": "run not found"})
                    return
                _json(self, 200, {"ok": True, "meta": meta})
                return

            if path == "/api/run/stream":
                run_id = (qs.get("run_id") or [""])[0].strip()
                meta = read_run_meta(root, cfg, run_id)
                if not meta:
                    self.send_response(404)
                    self.end_headers()
                    return
                # Stream .jsonl via SSE
                log_rel = meta.get("log_relpath") or ""
                log_path = root / log_rel if log_rel else (root / cfg.logs_dir / "runs" / f"{run_id}.jsonl")
                if not log_path.exists():
                    self.send_response(404)
                    self.end_headers()
                    return

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

                try:
                    self.wfile.write(b": ok\n\n")
                    self.wfile.flush()
                except Exception:
                    return

                try:
                    with log_path.open("r", encoding="utf-8") as f:
                        last_ping = time.time()
                        while True:
                            line = f.readline()
                            if line:
                                payload = line.strip()
                                try:
                                    self.wfile.write(("data: " + payload + "\n\n").encode("utf-8"))
                                    self.wfile.flush()
                                except Exception:
                                    break
                                continue

                            # no new line
                            meta2 = read_run_meta(root, cfg, run_id) or {}
                            st = str(meta2.get("status") or "")
                            if st in ["finished", "failed"]:
                                break
                            if time.time() - last_ping > 10:
                                try:
                                    self.wfile.write(b": ping\n\n")
                                    self.wfile.flush()
                                except Exception:
                                    break
                                last_ping = time.time()
                            time.sleep(0.4)
                except Exception:
                    return
                return

            # ----- Core status -----
            if path == "/api/status":
                state = load_state(st_file)
                ws = [w.__dict__ for w in list_workspaces(st_file)]
                locks = [l.__dict__ for l in list_locks(root=root, cfg=cfg)]
                mcp_cfg = load_mcp_config(root)
                payload = {
                    "ok": True,
                    "root": str(root),
                    "repo": cfg.repo,
                    "default_provider": cfg.default_provider,
                    "default_workflow": cfg.default_workflow,
                    "state": state,
                    "workspaces": ws,
                    "locks": locks,
                    "actions_enabled": bool(enable_actions),
                    "mcp": {"available": docker_mcp_available(), "profile": mcp_cfg.profile, "catalog_ref": mcp_cfg.catalog_ref},
                    "workflows": sorted(load_workflows(root).keys()),
                }
                _json(self, 200, payload)
                return

            if path == "/api/workflows":
                _json(self, 200, {"ok": True, "workflows": sorted(load_workflows(root).keys())})
                return

            # ----- Queue (read-only) -----
            if path == "/api/queue/issues":
                limit = int((qs.get("limit") or ["25"])[0])
                try:
                    issues = list_issues(label=cfg.queue_label, limit=limit)
                    _json(
                        self,
                        200,
                        {
                            "ok": True,
                            "label": cfg.queue_label,
                            "issues": [{"number": i.number, "title": i.title, "url": i.url, "labels": i.labels} for i in issues],
                        },
                    )
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/bootstrap/plan":
                agents_raw = (qs.get("agents") or [""])[0]
                take = int((qs.get("take") or ["3"])[0])
                wf = (qs.get("workflow") or [""])[0].strip() or None
                agents = [a.strip() for a in agents_raw.split(",") if a.strip()] if agents_raw else []
                try:
                    plan = build_plan_from_queue(root, cfg, agents=agents or None, take=take, label=cfg.queue_label, workflow_override=wf, prefer_unique_locks=True)
                    _json(self, 200, {"ok": True, "plan": [p.__dict__ for p in plan]})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            # ----- MCP (read-only) -----
            if path == "/api/mcp/config":
                mcfg = load_mcp_config(root)
                _json(self, 200, {"ok": True, "config": mcfg.__dict__})
                return

            if path == "/api/mcp/version":
                _json(self, 200, {"ok": True, "version": docker_mcp_version() or ""})
                return

            if path == "/api/mcp/catalog":
                filt = (qs.get("filter") or [""])[0].strip() or None
                mcfg = load_mcp_config(root)
                try:
                    ids = docker_catalog_server_ls(mcfg.catalog_ref)
                    if filt:
                        ids = [x for x in ids if filt.lower() in x.lower()]
                    _json(self, 200, {"ok": True, "servers": ids})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/mcp/profile":
                mcfg = load_mcp_config(root)
                try:
                    profs = docker_profile_list()
                    servers = docker_profile_server_ls(mcfg.profile)
                    _json(self, 200, {"ok": True, "profiles": profs, "profile": mcfg.profile, "servers": servers})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/mcp/gateway/list":
                try:
                    _json(self, 200, {"ok": True, "gateways": list_gateways(root, cfg)})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            _json(self, 404, {"ok": False, "error": "not found"})
            return

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            # Read request body
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                body = {}

            def require_auth() -> bool:
                if _check_auth(self):
                    return True
                _unauthorized(self)
                return False

            # ----- Actions (spawn/locks/workflow/bootstrap) -----
            if path == "/api/workspaces/spawn":
                if not require_auth():
                    return
                agent = str(body.get("agent") or "").strip()
                task = str(body.get("task") or "").strip()
                base_ref = str(body.get("base_ref") or cfg.default_base_ref)
                if not agent or not task:
                    _json(self, 400, {"ok": False, "error": "agent and task are required"})
                    return
                ws = spawn_workspace(root, cfg, pol, st_file, agent=agent, task=task, base_ref=base_ref)
                _json(self, 200, {"ok": True, "workspace": ws.__dict__})
                return

            if path == "/api/locks/acquire":
                if not require_auth():
                    return
                group = str(body.get("group") or "").strip()
                agent = str(body.get("agent") or "").strip()
                task = str(body.get("task") or "").strip()
                ttl = int(body.get("ttl_sec") or 6 * 60 * 60)
                if not group or not agent or not task:
                    _json(self, 400, {"ok": False, "error": "group, agent, task are required"})
                    return
                try:
                    info = acquire_lock(root=root, cfg=cfg, group=group, agent=agent, task=task, ttl_sec=ttl, force=False)
                    _json(self, 200, {"ok": True, "lock": info.__dict__})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/locks/release":
                if not require_auth():
                    return
                group = str(body.get("group") or "").strip()
                agent = str(body.get("agent") or "").strip()
                task = str(body.get("task") or "").strip()
                if not group:
                    _json(self, 400, {"ok": False, "error": "group required"})
                    return
                try:
                    release_lock(root=root, cfg=cfg, group=group, agent=agent or None, task=task or None, force=False)
                    _json(self, 200, {"ok": True})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/workflow/run":
                if not require_auth():
                    return
                agent = str(body.get("agent") or "").strip()
                task = str(body.get("task") or "").strip()
                workflow = str(body.get("workflow") or cfg.default_workflow).strip()
                if not agent or not task:
                    _json(self, 400, {"ok": False, "error": "agent and task required"})
                    return
                try:
                    summary = run_workflow(
                        root=root,
                        cfg=cfg,
                        pol=pol,
                        agent=agent,
                        task=task,
                        workflow=workflow,
                        provider_default=cfg.default_provider,
                        extra_ctx={},
                        dry_run=False,
                        log_json=True,
                        event_cb=None,
                    )
                    ok = all(r.ok for r in summary.results)
                    summary_j = json.loads(json.dumps(summary, default=lambda o: o.__dict__))
                    _json(self, 200, {"ok": True, "ok_run": ok, "summary": summary_j})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/workflow/run_async":
                if not require_auth():
                    return
                agent = str(body.get("agent") or "").strip()
                task = str(body.get("task") or "").strip()
                workflow = str(body.get("workflow") or cfg.default_workflow).strip()
                if not agent or not task:
                    _json(self, 400, {"ok": False, "error": "agent and task required"})
                    return

                run_id = secrets.token_hex(16)
                title = f"workflow:{workflow} {agent}:{task}"
                create_run(root, cfg, kind="workflow", title=title, run_id=run_id)

                def cb(ev: Dict[str, Any]) -> None:
                    append_event(root, cfg, run_id, ev)

                def worker() -> None:
                    try:
                        cb({"type": "run_start", "kind": "workflow", "workflow": workflow, "agent": agent, "task": task})
                        summary = run_workflow(
                            root=root,
                            cfg=cfg,
                            pol=pol,
                            agent=agent,
                            task=task,
                            workflow=workflow,
                            provider_default=cfg.default_provider,
                            extra_ctx={},
                            dry_run=False,
                            log_json=True,
                            event_cb=cb,
                        )
                        ok = all(r.ok for r in summary.results)
                        summary_j = json.loads(json.dumps(summary, default=lambda o: o.__dict__))
                        update_run_meta(
                            root,
                            cfg,
                            run_id,
                            patch={"status": "finished" if ok else "failed", "finished_ts": _now(), "ok": ok, "summary": summary_j},
                        )
                        cb({"type": "run_end", "ok": ok, "pr_url": summary.pr_url})
                    except Exception as e:
                        cb({"type": "error", "error": str(e)})
                        update_run_meta(root, cfg, run_id, patch={"status": "failed", "finished_ts": _now(), "error": str(e)})

                threading.Thread(target=worker, daemon=True).start()
                _json(self, 200, {"ok": True, "run_id": run_id})
                return

            if path == "/api/bootstrap/run_async":
                if not require_auth():
                    return
                agents = body.get("agents") or []
                if isinstance(agents, str):
                    agents = [a.strip() for a in agents.split(",") if a.strip()]
                if not isinstance(agents, list):
                    agents = []
                agents = [str(a).strip() for a in agents if str(a).strip()]
                take = int(body.get("take") or 3)
                fast = bool(body.get("fast") if "fast" in body else True)
                claim = bool(body.get("claim") if "claim" in body else False)
                create_prs = bool(body.get("create_prs") if "create_prs" in body else True)
                draft_prs = bool(body.get("draft_prs") if "draft_prs" in body else True)
                workflow_override = body.get("workflow_override") if body.get("workflow_override") not in ["", None] else None

                run_id = secrets.token_hex(16)
                title = f"bootstrap take={take} agents={','.join(agents) or '(default)'}"
                create_run(root, cfg, kind="bootstrap", title=title, run_id=run_id)

                def cb(ev: Dict[str, Any]) -> None:
                    append_event(root, cfg, run_id, ev)

                def worker() -> None:
                    try:
                        cb({"type": "run_start", "kind": "bootstrap"})
                        run_bootstrap(
                            root,
                            cfg,
                            pol,
                            agents=agents or ["a1", "a2", "a3"],
                            take=take,
                            fast=fast,
                            claim=claim,
                            create_prs=create_prs,
                            draft_prs=draft_prs,
                            run_daemon=False,
                            workflow_override=workflow_override,
                            event_cb=cb,
                        )
                        update_run_meta(root, cfg, run_id, patch={"status": "finished", "finished_ts": _now()})
                        cb({"type": "run_end", "ok": True})
                    except Exception as e:
                        cb({"type": "error", "error": str(e)})
                        update_run_meta(root, cfg, run_id, patch={"status": "failed", "finished_ts": _now(), "error": str(e)})

                threading.Thread(target=worker, daemon=True).start()
                _json(self, 200, {"ok": True, "run_id": run_id})
                return

            # ----- MCP actions -----
            if path == "/api/mcp/sync":
                if not require_auth():
                    return
                mcfg = load_mcp_config(root)
                try:
                    docker_sync_profile(mcfg)
                    _json(self, 200, {"ok": True, "profile": mcfg.profile, "servers": mcfg.servers})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/mcp/profile/add":
                if not require_auth():
                    return
                server = str(body.get("server") or "").strip()
                if not server:
                    _json(self, 400, {"ok": False, "error": "server required"})
                    return
                mcfg = load_mcp_config(root)
                try:
                    docker_profile_server_add(mcfg.profile, mcfg.catalog_ref, server_id=server)
                    _json(self, 200, {"ok": True})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/mcp/profile/remove":
                if not require_auth():
                    return
                name = str(body.get("name") or "").strip()
                if not name:
                    _json(self, 400, {"ok": False, "error": "name required"})
                    return
                mcfg = load_mcp_config(root)
                try:
                    docker_profile_server_remove(mcfg.profile, name=name)
                    _json(self, 200, {"ok": True})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/mcp/gateway/start":
                if not require_auth():
                    return
                key = body.get("key")
                if key is not None:
                    key = str(key).strip() or None
                transport = body.get("transport")
                if transport is not None:
                    transport = str(transport).strip() or None
                try:
                    mcfg = load_mcp_config(root)
                    gw = ensure_gateway_running(root, cfg, mcfg, key=key, transport=transport)
                    _json(self, 200, {"ok": True, "gateway": gw})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            if path == "/api/mcp/gateway/stop":
                if not require_auth():
                    return
                key = body.get("key")
                if key is not None:
                    key = str(key).strip() or None
                try:
                    stop_gateway(root, cfg, key=key)
                    _json(self, 200, {"ok": True})
                except Exception as e:
                    _json(self, 500, {"ok": False, "error": str(e)})
                return

            _json(self, 404, {"ok": False, "error": "not found"})
            return

    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"[agentforge ui] http://{host}:{port}")
    if enable_actions:
        print(f"[agentforge ui] actions enabled; use token: {token}")
    srv.serve_forever()
