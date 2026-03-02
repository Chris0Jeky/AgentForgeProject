from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None

from .utils import run, which, ensure_dir, atomic_write_text


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
    return which("docker") is not None and run(["docker", "mcp", "version"], capture=True).ok


def docker_mcp_version() -> Optional[str]:
    if not docker_mcp_available():
        return None
    r = run(["docker", "mcp", "version"], capture=True)
    if not r.ok:
        return None
    return (r.stdout or "").strip()


def docker_catalog_server_ls(catalog_ref: str) -> List[str]:
    r = run(["docker", "mcp", "server", "list", "--catalog", catalog_ref], capture=True)
    if not r.ok:
        raise McpError(r.stderr or r.stdout or "docker mcp server list failed")
    # Output is one server id per line.
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    # Some versions include headers; keep only token-like first col.
    out: List[str] = []
    for ln in lines:
        if ln.lower().startswith("id") and "description" in ln.lower():
            continue
        out.append(ln.split()[0])
    return out


def docker_profile_list() -> List[str]:
    r = run(["docker", "mcp", "profile", "list"], capture=True)
    if not r.ok:
        raise McpError(r.stderr or r.stdout or "docker mcp profile list failed")
    # best-effort parse: lines are profile names
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    out: List[str] = []
    for ln in lines:
        if ln.lower().startswith("name"):
            continue
        out.append(ln.split()[0])
    return out


def docker_profile_server_ls(profile: str) -> List[Dict[str, Any]]:
    r = run(["docker", "mcp", "profile", "server", "list", "--profile", profile, "--format", "json"], capture=True)
    if not r.ok:
        # Older versions may not support --format json; fall back to text.
        r2 = run(["docker", "mcp", "profile", "server", "list", "--profile", profile], capture=True)
        if not r2.ok:
            raise McpError(r.stderr or r2.stderr or r.stdout or r2.stdout or "docker mcp profile server list failed")
        lines = [ln.strip() for ln in (r2.stdout or "").splitlines() if ln.strip()]
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
        return json.loads(r.stdout or "[]")
    except Exception:
        return []


def docker_profile_create(profile: str) -> None:
    r = run(["docker", "mcp", "profile", "create", "--profile", profile], capture=True)
    if not r.ok:
        # If it already exists, ignore.
        if "already exists" in (r.stderr or "").lower():
            return
        raise McpError(r.stderr or r.stdout or "docker mcp profile create failed")


def docker_profile_server_add(profile: str, catalog_ref: str, *, server_id: str) -> None:
    r = run(
        ["docker", "mcp", "profile", "server", "add", "--profile", profile, "--catalog", catalog_ref, server_id],
        capture=True,
    )
    if not r.ok:
        raise McpError(r.stderr or r.stdout or "docker mcp profile server add failed")


def docker_profile_server_remove(profile: str, *, name: str) -> None:
    r = run(["docker", "mcp", "profile", "server", "remove", "--profile", profile, name], capture=True)
    if not r.ok:
        raise McpError(r.stderr or r.stdout or "docker mcp profile server remove failed")


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


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _load_gateways(root: Path, cfg) -> Dict[str, Dict[str, Any]]:
    p = _gateways_path(root, cfg)
    if not p.exists():
        return {}
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
        return dict(j or {})
    except Exception:
        return {}


def _save_gateways(root: Path, cfg, gws: Dict[str, Dict[str, Any]]) -> None:
    p = _gateways_path(root, cfg)
    ensure_dir(p.parent)
    atomic_write_text(p, json.dumps(gws, indent=2))


def _find_free_port(host: str, start: int, end: int) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    # fallback: ephemeral
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def list_gateways(root: Path, cfg) -> List[Dict[str, Any]]:
    """List known gateways (best-effort). Removes stale entries."""
    gws = _load_gateways(root, cfg)
    changed = False
    out: List[Dict[str, Any]] = []
    for k, v in list(gws.items()):
        pid = int(v.get("pid") or 0)
        if pid and not _pid_alive(pid):
            del gws[k]
            changed = True
            continue
        out.append(dict(v))
    if changed:
        _save_gateways(root, cfg, gws)
    out.sort(key=lambda x: str(x.get("key") or ""))
    return out


def ensure_gateway_running(
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
    if not docker_mcp_available():
        raise McpError("docker mcp not available")

    gw_key = key or "__global__"
    gws = _load_gateways(root, cfg)
    existing = gws.get(gw_key)
    if existing:
        pid = int(existing.get("pid") or 0)
        if pid and _pid_alive(pid):
            return dict(existing)
        # stale entry
        gws.pop(gw_key, None)

    t = (transport or mcfg.gateway_transport or "sse").strip().lower()
    if t in ["stdio"]:
        raise McpError("gateway transport 'stdio' cannot be managed as a background process. Use sse/streaming.")

    if mcfg.gateway_auto_sync:
        docker_sync_profile(mcfg)

    port = _find_free_port(mcfg.gateway_bind_host, int(mcfg.gateway_port_start), int(mcfg.gateway_port_end))
    auth = secrets.token_hex(16)

    cmd = ["docker", "mcp", "gateway", "run", "--profile", mcfg.profile, "--transport", t, "--port", str(port)]
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

    with log_path.open("ab") as lf:
        p = subprocess.Popen(cmd, cwd=str(root), stdout=lf, stderr=lf, env=env)

    url = f"http://{mcfg.gateway_bind_host}:{port}"
    info = {
        "key": gw_key if gw_key != "__global__" else "",
        "profile": mcfg.profile,
        "transport": t,
        "port": port,
        "url": url,
        "pid": p.pid,
        "auth_token": auth,
        "log_path": str(log_path),
        "started_ts": int(time.time()),
    }
    gws[gw_key] = info
    _save_gateways(root, cfg, gws)
    return dict(info)


def stop_gateway(root: Path, cfg, *, key: Optional[str] = None) -> None:
    gw_key = key or "__global__"
    gws = _load_gateways(root, cfg)
    info = gws.get(gw_key)
    if not info:
        return
    pid = int(info.get("pid") or 0)
    if pid and _pid_alive(pid):
        try:
            # Best-effort terminate.
            os.kill(pid, 15)
        except Exception:
            pass
    gws.pop(gw_key, None)
    _save_gateways(root, cfg, gws)
