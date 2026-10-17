from __future__ import annotations

import http.client
import json
import signal
import os
import secrets
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None

from .file_mutex import file_mutex
from .utils import CommandError, run, which, ensure_dir, atomic_write_text


class McpError(RuntimeError):
    pass


@dataclass(frozen=True)
class McpConfig:
    backend: str = "docker"  # currently: docker
    catalog_ref: str = "mcp/docker-mcp-catalog"
    profile: str = "agentforge"
    servers: List[str] = field(default_factory=list)

    # Gateway (optional)
    gateway_auto_start: bool = False
    gateway_inject_prompt: bool = True
    gateway_transport: str = "sse"  # sse | streaming | stdio
    gateway_port_start: int = 9360
    gateway_port_end: int = 9460
    gateway_per_workspace: bool = True
    gateway_log_calls: bool = False
    gateway_watch: bool = True
    gateway_long_lived: bool = False
    gateway_verify_signatures: bool = False
    gateway_auto_sync: bool = True
    gateway_bind_host: str = "127.0.0.1"


def docker_mcp_available() -> bool:
    if which("docker") is None:
        return False
    try:
        run(["docker", "mcp", "version"], capture=True)
        return True
    except Exception:
        return False


def docker_mcp_version() -> Optional[str]:
    if which("docker") is None:
        return None
    try:
        _, stdout, _ = run(["docker", "mcp", "version"], capture=True)
    except Exception:
        return None
    return (stdout or "").strip()


def docker_catalog_server_ls(catalog_ref: str) -> List[str]:
    try:
        _, stdout, _ = run(["docker", "mcp", "server", "list", "--catalog", catalog_ref], capture=True)
    except CommandError as e:
        raise McpError(e.stderr or e.stdout or "docker mcp server list failed") from e
    # Output is one server id per line.
    lines = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
    # Some versions include headers; keep only token-like first col.
    out: List[str] = []
    for ln in lines:
        if ln.lower().startswith("id") and "description" in ln.lower():
            continue
        out.append(ln.split()[0])
    return out


def docker_profile_list() -> List[str]:
    try:
        _, stdout, _ = run(["docker", "mcp", "profile", "list"], capture=True)
    except CommandError as e:
        raise McpError(e.stderr or e.stdout or "docker mcp profile list failed") from e
    # best-effort parse: lines are profile names
    lines = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
    out: List[str] = []
    for ln in lines:
        if ln.lower().startswith("name"):
            continue
        out.append(ln.split()[0])
    return out


def docker_profile_server_ls(profile: str) -> List[Dict[str, Any]]:
    try:
        _, stdout, _ = run(
            ["docker", "mcp", "profile", "server", "list", "--profile", profile, "--format", "json"],
            capture=True,
        )
    except CommandError as e_json:
        # Older versions may not support --format json; fall back to text.
        try:
            _, txt_out, _ = run(["docker", "mcp", "profile", "server", "list", "--profile", profile], capture=True)
        except CommandError as e_txt:
            raise McpError(
                e_json.stderr or e_txt.stderr or e_json.stdout or e_txt.stdout or "docker mcp profile server list failed"
            ) from e_txt
        lines = [ln.strip() for ln in (txt_out or "").splitlines() if ln.strip()]
        out: List[Dict[str, Any]] = []
        for ln in lines:
            if ln.lower().startswith("name") and "id" in ln.lower():
                continue
            parts = ln.split()
            if not parts:
                continue
            out.append({"name": parts[0], "id": parts[1] if len(parts) > 1 else ""})
        return out
    try:
        return json.loads(stdout or "[]")
    except Exception:
        return []


def docker_profile_create(profile: str) -> None:
    try:
        run(["docker", "mcp", "profile", "create", "--profile", profile], capture=True)
    except CommandError as e:
        # If it already exists, ignore.
        if "already exists" in (e.stderr or "").lower():
            return
        raise McpError(e.stderr or e.stdout or "docker mcp profile create failed") from e


def docker_profile_server_add(profile: str, catalog_ref: str, *, server_id: str) -> None:
    try:
        run(
            ["docker", "mcp", "profile", "server", "add", "--profile", profile, "--catalog", catalog_ref, server_id],
            capture=True,
        )
    except CommandError as e:
        raise McpError(e.stderr or e.stdout or "docker mcp profile server add failed") from e


def docker_profile_server_remove(profile: str, *, name: str) -> None:
    try:
        run(["docker", "mcp", "profile", "server", "remove", "--profile", profile, name], capture=True)
    except CommandError as e:
        raise McpError(e.stderr or e.stdout or "docker mcp profile server remove failed") from e


def docker_sync_profile(cfg: McpConfig) -> None:
    if cfg.backend != "docker":
        raise McpError(f"Unsupported MCP backend: {cfg.backend}")
    if not docker_mcp_available():
        raise McpError("docker mcp is not available. Install/enable Docker MCP Toolkit first.")
    docker_profile_create(cfg.profile)
    # Add all configured servers (best-effort).
    existing = {x.get("name") for x in docker_profile_server_ls(cfg.profile)}
    for sid in cfg.servers:
        if sid in existing:
            continue
        docker_profile_server_add(cfg.profile, cfg.catalog_ref, server_id=sid)


def load_mcp_config(root: Path) -> McpConfig:
    """Load `.agentforge/mcp.toml` if present, else defaults."""
    path = root / ".agentforge" / "mcp.toml"
    if not path.exists():
        return McpConfig()

    if tomllib is None:
        raise SystemExit("Python 3.11+ required for tomllib.")

    data = tomllib.loads(path.read_text(encoding="utf-8")) or {}
    servers = list(data.get("servers") or [])
    gateway = data.get("gateway") or {}

    def _b(x: Any, default: bool) -> bool:
        if isinstance(x, bool):
            return x
        if x is None:
            return default
        s = str(x).strip().lower()
        if s in ["1", "true", "yes", "on", "y"]:
            return True
        if s in ["0", "false", "no", "off", "n"]:
            return False
        return default

    return McpConfig(
        backend=str(data.get("backend") or "docker"),
        catalog_ref=str(data.get("catalog_ref") or "mcp/docker-mcp-catalog"),
        profile=str(data.get("profile") or "agentforge"),
        servers=[str(x) for x in servers if str(x).strip()],
        gateway_auto_start=_b(gateway.get("auto_start"), False),
        gateway_inject_prompt=_b(gateway.get("inject_prompt"), True),
        gateway_transport=str(gateway.get("transport") or "sse"),
        gateway_port_start=int(gateway.get("port_start") or 9360),
        gateway_port_end=int(gateway.get("port_end") or 9460),
        gateway_per_workspace=_b(gateway.get("per_workspace"), True),
        gateway_log_calls=_b(gateway.get("log_calls"), False),
        gateway_watch=_b(gateway.get("watch"), True),
        gateway_long_lived=_b(gateway.get("long_lived"), False),
        gateway_verify_signatures=_b(gateway.get("verify_signatures"), False),
        gateway_auto_sync=_b(gateway.get("auto_sync"), True),
        gateway_bind_host=str(gateway.get("bind_host") or "127.0.0.1"),
    )


def _gateways_path(root: Path, cfg) -> Path:
    return root / cfg.state_dir / "mcp_gateways.json"


# A saved PID cannot establish ownership after a coordinator restart.
_gateway_processes: Dict[tuple, tuple] = {}


def _owned_process(root: Path, cfg, info: dict):
    owned = _gateway_processes.get((str(_gateways_path(root, cfg).resolve()), info.get("operation_id")))
    if owned:
        process, pidfd, intent = owned
        if all(info.get(k) == intent.get(k) for k in ("operation_id", "command", "port", "auth_token", "url")):
            if not info.get("pid") or info["pid"] == process.pid:
                return owned
    raise McpError("Gateway ownership is unprovable; reconcile the retained gateway record and OS process manually.")


def _gateway_ready(info: dict) -> bool:
    # The fresh launch token must be enforced by this endpoint before it is advertised.
    path = "/sse" if info["transport"] == "sse" else "/mcp"
    url = urlsplit(info["url"])
    statuses = []
    try:
        for headers in ({}, {"Authorization": "Bearer " + info["auth_token"]}):
            conn = http.client.HTTPConnection(url.hostname, url.port, timeout=0.2)
            try:
                conn.request("GET", path, headers=headers)
                statuses.append(conn.getresponse().status)
            finally:
                conn.close()
    except (OSError, http.client.HTTPException):
        return False
    return statuses[0] in (401, 403) and statuses[1] == 200


def _load_gateways(root: Path, cfg) -> Dict[str, Dict[str, Any]]:
    p = _gateways_path(root, cfg)
    if not p.exists():
        return {}
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(j, dict) or any(not isinstance(v, dict) for v in j.values()):
            raise ValueError("Expected gateway records keyed by gateway identity")
        return j
    except Exception as e:
        raise McpError("Gateway registry is unreadable; reconcile it before starting or stopping gateways.") from e


def _save_gateways(root: Path, cfg, gws: Dict[str, Dict[str, Any]]) -> None:
    p = _gateways_path(root, cfg)
    ensure_dir(p.parent)
    atomic_write_text(p, json.dumps(gws, indent=2))


def _find_free_port(host: str, start: int, end: int, reserved=None) -> int:
    for port in range(start, end + 1):
        if port in (reserved or set()):
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise McpError("No unreserved gateway port is available in the configured range.")


def gateway_status(info: Dict[str, Any]) -> Dict[str, Any]:
    """Public status only; credentials stay in the private gateway store."""
    status = {k: info[k] for k in ("key", "profile", "transport", "pid") if k in info}
    status["url"] = ""
    try:
        url = urlsplit(str(info.get("url") or ""))
        if url.scheme in {"http", "https"} and url.hostname:
            host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
            port = f":{url.port}" if url.port is not None else ""
            status["url"] = f"{url.scheme}://{host}{port}"
    except ValueError:
        pass
    return status


def list_gateways(root: Path, cfg) -> List[Dict[str, Any]]:
    """Observe retained records without deleting unresolved ownership evidence."""
    with file_mutex(_gateways_path(root, cfg).with_suffix(".mutex")):
        out = []
        for info in _load_gateways(root, cfg).values():
            status = gateway_status(info)
            status["state"] = "unresolved"
            try:
                process, _, _ = _owned_process(root, cfg, info)
                status["state"] = "exited" if process.poll() is not None else info.get("state", "unresolved")
            except (McpError, OSError):
                pass
            out.append(status)
        return sorted(out, key=lambda x: str(x.get("key") or ""))


def _ensure_gateway_running(
    root: Path,
    cfg,
    mcfg: McpConfig,
    *,
    key: Optional[str] = None,
    transport: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure a Docker MCP Gateway is running.

    key:
      - None => repo/global gateway
      - string => workspace-scoped gateway key (e.g. "a1::issue-123")

    transport: optional override for this start.
    """
    gw_key = key or "__global__"
    gws = _load_gateways(root, cfg)
    existing = gws.get(gw_key)
    if existing:
        process, _, _ = _owned_process(root, cfg, existing)
        if process.poll() is None and _gateway_ready(existing) and process.poll() is None:
            existing.update(pid=process.pid, state="running")
            _save_gateways(root, cfg, gws)
            return dict(existing)
        raise McpError("Gateway exited or launch is unresolved; reconcile the retained record before restarting.")
    if not docker_mcp_available():
        raise McpError("docker mcp not available")
    if os.name != "nt" and not (hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")):
        raise McpError("Safe gateway process handles are unavailable on this platform.")

    t = (transport or mcfg.gateway_transport or "sse").strip().lower()
    if t in ["stdio"]:
        raise McpError("gateway transport 'stdio' cannot be managed as a background process. Use sse/streaming.")

    if mcfg.gateway_auto_sync:
        docker_sync_profile(mcfg)

    used_ports = {int(v["port"]) for v in gws.values() if v.get("port")}
    port = _find_free_port(mcfg.gateway_bind_host, int(mcfg.gateway_port_start), int(mcfg.gateway_port_end), used_ports)
    auth = secrets.token_hex(16)

    cmd = [which("docker") or "docker", "mcp", "gateway", "run", "--profile", mcfg.profile, "--transport", t, "--port", str(port)]
    if mcfg.gateway_log_calls:
        cmd += ["--log-calls"]
    if mcfg.gateway_watch:
        cmd += ["--watch"]
    if mcfg.gateway_long_lived:
        cmd += ["--long-lived"]
    if mcfg.gateway_verify_signatures:
        cmd += ["--verify-signatures"]

    # log file
    log_dir = root / cfg.logs_dir / "mcp"
    ensure_dir(log_dir)
    safe_key = gw_key.replace("/", "_").replace(":", "_")
    log_path = log_dir / f"gateway-{safe_key}.log"

    env = os.environ.copy()
    env["MCP_GATEWAY_AUTH_TOKEN"] = auth

    url = f"http://{mcfg.gateway_bind_host}:{port}"
    info = {
        "key": gw_key if gw_key != "__global__" else "",
        "profile": mcfg.profile,
        "transport": t,
        "port": port,
        "url": url,
        "pid": None,
        "auth_token": auth,
        "log_path": str(log_path),
        "started_ts": int(time.time()),
        "operation_id": secrets.token_hex(16),
        "command": cmd,
        "state": "launching",
    }
    gws[gw_key] = info
    _save_gateways(root, cfg, gws)
    # The durable intent reserves this port against other AgentForge launches.
    with log_path.open("ab") as lf:
        process = subprocess.Popen(cmd, cwd=str(root), stdout=lf, stderr=lf, env=env)
    # An unreaped child PID cannot be reused before pidfd_open binds the handle.
    pidfd = os.pidfd_open(process.pid) if os.name != "nt" else None
    _gateway_processes[(str(_gateways_path(root, cfg).resolve()), info["operation_id"])] = (process, pidfd, dict(info))
    info["pid"] = process.pid
    _save_gateways(root, cfg, gws)
    deadline = time.monotonic() + 3
    while process.poll() is None and time.monotonic() < deadline:
        if _gateway_ready(info) and process.poll() is None:
            info["state"] = "running"
            _save_gateways(root, cfg, gws)
            return dict(info)
        time.sleep(0.05)
    info["state"] = "unresolved"
    _save_gateways(root, cfg, gws)
    raise McpError("Gateway endpoint ownership could not be attested; reconcile the retained launch record.")


def ensure_gateway_running(root: Path, cfg, mcfg: McpConfig, *, key: Optional[str] = None,
                           transport: Optional[str] = None) -> Dict[str, Any]:
    with file_mutex(_gateways_path(root, cfg).with_suffix(".mutex")):
        return _ensure_gateway_running(root, cfg, mcfg, key=key, transport=transport)


def stop_gateway(root: Path, cfg, *, key: Optional[str] = None) -> None:
    with file_mutex(_gateways_path(root, cfg).with_suffix(".mutex")):
        gw_key = key or "__global__"
        gws = _load_gateways(root, cfg)
        info = gws.get(gw_key)
        if not info:
            return
        process, pidfd, _ = _owned_process(root, cfg, info)
        try:
            if process.poll() is None:
                if os.name == "nt":
                    process.terminate()  # Popen retains the Windows process handle.
                else:
                    signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise McpError("Gateway stop unconfirmed; reconcile the retained record.") from e
        gws.pop(gw_key)
        _save_gateways(root, cfg, gws)
        _gateway_processes.pop((str(_gateways_path(root, cfg).resolve()), info.get("operation_id")), None)
        if pidfd is not None:
            os.close(pidfd)
