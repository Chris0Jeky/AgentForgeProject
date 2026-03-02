from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None

from .utils import out, run, which, CommandError


@dataclass(frozen=True)
class McpConfig:
    backend: str = "docker"  # currently: docker
    catalog_ref: str = "mcp/docker-mcp-catalog"
    profile: str = "agentforge"
    servers: List[str] = field(default_factory=list)


def load_mcp_config(root: Path) -> McpConfig:
    """Load `.agentforge/mcp.toml` if present; otherwise return defaults."""
    path = root / ".agentforge" / "mcp.toml"
    if not path.exists():
        return McpConfig(servers=[])
    if tomllib is None:
        raise SystemExit("Python 3.11+ required for tomllib.")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    backend = str(data.get("backend") or "docker").strip() or "docker"
    catalog_ref = str(data.get("catalog_ref") or "mcp/docker-mcp-catalog").strip() or "mcp/docker-mcp-catalog"
    profile = str(data.get("profile") or "agentforge").strip() or "agentforge"
    servers = [str(s) for s in list(data.get("servers") or [])]
    return McpConfig(backend=backend, catalog_ref=catalog_ref, profile=profile, servers=servers)


# ----------------------------
# Docker MCP backend
# ----------------------------

class McpBackendError(RuntimeError):
    pass


def docker_mcp_available() -> bool:
    if which("docker") is None:
        return False
    try:
        out(["docker", "mcp", "--help"])
        return True
    except Exception:
        return False


def _docker_mcp(cmd: List[str]) -> str:
    if which("docker") is None:
        raise McpBackendError("docker not found")
    return out(["docker", "mcp"] + cmd)


def docker_mcp_version() -> Optional[str]:
    try:
        # Some versions support: docker mcp version
        return _docker_mcp(["version"])
    except Exception:
        return None


def docker_profile_list() -> List[str]:
    """Return profile IDs."""
    txt = _docker_mcp(["profile", "list"])
    # Expected table output; first column is profile id.
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    if not lines:
        return []
    # drop header if it contains 'PROFILE' or similar
    if "profile" in lines[0].lower():
        lines = lines[1:]
    ids: List[str] = []
    for ln in lines:
        ids.append(ln.split()[0])
    return ids


def docker_profile_create(profile_id: str) -> None:
    _docker_mcp(["profile", "create", "--name", profile_id])


def docker_profile_show(profile_id: str) -> str:
    return _docker_mcp(["profile", "show", profile_id])


def docker_profile_server_ls(profile_id: Optional[str] = None) -> str:
    cmd = ["profile", "server", "ls"]
    if profile_id:
        cmd += ["--filter", f"profile={profile_id}"]
    return _docker_mcp(cmd)


def docker_profile_server_add(profile_id: str, *, catalog_ref: str, server_ids: List[str]) -> None:
    if not server_ids:
        return
    cmd = ["profile", "server", "add", profile_id]
    for sid in server_ids:
        sid = sid.strip()
        if not sid:
            continue
        cmd += ["--server", f"catalog://{catalog_ref}/{sid}"]
    _docker_mcp(cmd)


def docker_profile_server_remove(profile_id: str, *, server_names: List[str]) -> None:
    if not server_names:
        return
    cmd = ["profile", "server", "remove", profile_id]
    for name in server_names:
        name = name.strip()
        if not name:
            continue
        cmd += ["--name", name]
    _docker_mcp(cmd)


def docker_catalog_server_ls(catalog_ref: str) -> List[str]:
    """List server IDs in a catalog.

    We try JSON formatting if supported; otherwise parse the table output.
    """
    # Try: docker mcp catalog server ls <ref> --format=json (not guaranteed across versions)
    try:
        txt = _docker_mcp(["catalog", "server", "ls", catalog_ref, "--format=json"])
        j = json.loads(txt)
        # expect list of objects with 'server_id' or similar
        ids: List[str] = []
        if isinstance(j, list):
            for it in j:
                if isinstance(it, dict):
                    for key in ["server_id", "id", "name", "Server ID", "serverId"]:
                        if key in it:
                            ids.append(str(it[key]))
                            break
            if ids:
                return ids
    except Exception:
        pass

    txt = _docker_mcp(["catalog", "server", "ls", catalog_ref])
    lines = [ln.rstrip() for ln in txt.splitlines() if ln.strip()]
    if not lines:
        return []
    # If table has headers, assume first column is Server ID.
    if "server" in lines[0].lower() and "id" in lines[0].lower():
        lines = lines[1:]
    ids: List[str] = []
    for ln in lines:
        ids.append(ln.split()[0])
    # Deduplicate while preserving order
    seen = set()
    out_ids: List[str] = []
    for x in ids:
        if x not in seen:
            out_ids.append(x)
            seen.add(x)
    return out_ids


def docker_ensure_profile(cfg: McpConfig) -> None:
    if not docker_mcp_available():
        raise McpBackendError("docker mcp not available. Install Docker Desktop (MCP Toolkit) or the docker-mcp CLI plugin.")
    existing = set(docker_profile_list())
    if cfg.profile not in existing:
        docker_profile_create(cfg.profile)


def docker_sync_profile(cfg: McpConfig) -> None:
    """Ensure profile exists and contains cfg.servers (best-effort).

    This does **not** configure OAuth/secrets; those are handled by Docker Desktop / user.
    """
    docker_ensure_profile(cfg)
    # Add requested servers
    docker_profile_server_add(cfg.profile, catalog_ref=cfg.catalog_ref, server_ids=list(cfg.servers or []))
