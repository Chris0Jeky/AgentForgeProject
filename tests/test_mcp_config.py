from pathlib import Path

from agentforge.core.mcp import load_mcp_config


def test_load_mcp_defaults(tmp_path: Path):
    root = tmp_path
    (root / ".agentforge").mkdir()
    cfg = load_mcp_config(root)
    assert cfg.backend == "docker"
    assert cfg.profile == "agentforge"
    assert cfg.catalog_ref == "mcp/docker-mcp-catalog"
    assert cfg.servers == []


def test_load_mcp_file(tmp_path: Path):
    root = tmp_path
    af = root / ".agentforge"
    af.mkdir()
    (af / "mcp.toml").write_text(
        """backend = "docker"
catalog_ref = "mcp/docker-mcp-catalog"
profile = "myprof"
servers = ["playwright", "github-official"]
""",
        encoding="utf-8",
    )
    cfg = load_mcp_config(root)
    assert cfg.profile == "myprof"
    assert "playwright" in cfg.servers
