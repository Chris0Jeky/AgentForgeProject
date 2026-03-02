from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional, Tuple

from .config import RepoConfig, Policy
from .state import load_state
from .workspace import list_workspaces

def serve_status(root: Path, cfg: RepoConfig, pol: Policy, state_file: Path, host: str="127.0.0.1", port: int=5179) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path not in ["/", "/status", "/status.json"]:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            wss = list_workspaces(state_file)
            st = load_state(state_file)
            payload = {
                "repo_root": str(root),
                "repo": cfg.repo,
                "workspaces": [ws.__dict__ for ws in wss],
                "ports": st.get("ports", {}),
                "policy": {
                    "mode": pol.mode,
                    "deny_forks": pol.deny_forks,
                    "allowed_comment_authors": pol.allowed_comment_authors,
                },
            }
            if self.path == "/status.json":
                raw = json.dumps(payload, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            # simple HTML view
            rows = []
            for ws in wss:
                rows.append(
                    f"<tr><td>{html.escape(ws.agent)}</td><td>{html.escape(ws.task)}</td>"
                    f"<td><code>{html.escape(ws.branch)}</code></td>"
                    f"<td><code>{html.escape(ws.path)}</code></td>"
                    f"<td>{ws.port}</td></tr>"
                )
            table = (
                "<table border='1' cellspacing='0' cellpadding='6'>"
                "<tr><th>agent</th><th>task</th><th>branch</th><th>path</th><th>port</th></tr>"
                + "".join(rows) + "</table>"
            )
            body = f"""<html>
<head><title>AgentForge</title></head>
<body>
<h1>AgentForge status</h1>
<p><b>Repo:</b> {html.escape(cfg.repo or "(not set)")}</p>
<p><b>Root:</b> <code>{html.escape(str(root))}</code></p>
<h2>Workspaces</h2>
{table}
<h2>Useful commands</h2>
<pre>
agentforge list
agentforge spawn --agent a1 --task issue-123
agentforge run --agent a1 --task issue-123 --role implement --provider {html.escape(cfg.default_provider)} --auto-commit --auto-push --prompt "..."
agentforge daemon
</pre>
<p>JSON: <a href="/status.json">/status.json</a></p>
</body></html>"""
            raw = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # noqa: A003
            # Quiet
            return

    httpd = HTTPServer((host, port), Handler)
    print(f"AgentForge dashboard: http://{host}:{port}/")
    httpd.serve_forever()
