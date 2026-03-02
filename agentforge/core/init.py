from __future__ import annotations

from pathlib import Path
import importlib.resources as pkg_resources

from .utils import ensure_dir

TEMPLATE_DIR = "agentforge.templates"

def _copy_template(name: str, dest: Path, overwrite: bool) -> None:
    if dest.exists() and not overwrite:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = pkg_resources.files(TEMPLATE_DIR).joinpath(name).read_text(encoding="utf-8")
    dest.write_text(content, encoding="utf-8")

def init_repo(root: Path, overwrite: bool=False) -> None:
    af_dir = root / ".agentforge"
    ensure_dir(af_dir)
    ensure_dir(af_dir / "state")
    ensure_dir(af_dir / "logs")
    ensure_dir(af_dir / "cache")
    ensure_dir(af_dir / "prompts")

    # Keep state/log/cache uncommitted, but commit configs/policies.
    gi = af_dir / ".gitignore"
    if not gi.exists() or overwrite:
        gi.write_text("state/\nlogs/\ncache/\n", encoding="utf-8")

    _copy_template("config.toml", af_dir / "config.toml", overwrite=overwrite)
    _copy_template("policy.toml", af_dir / "policy.toml", overwrite=overwrite)
    _copy_template("AGENTFORGE_RULES.md", af_dir / "AGENTFORGE_RULES.md", overwrite=overwrite)

    # New: workflows + locks
    _copy_template("workflows.toml", af_dir / "workflows.toml", overwrite=overwrite)
    _copy_template("locks.toml", af_dir / "locks.toml", overwrite=overwrite)
    _copy_template("mcp.toml", af_dir / "mcp.toml", overwrite=overwrite)

    # Prompt templates
    _copy_template("issue_implement.md", af_dir / "prompts" / "issue_implement.md", overwrite=overwrite)

    # GitHub workflow templates
    _copy_template("agentforge-wake.yml", root / ".github" / "workflows" / "agentforge-wake.yml", overwrite=overwrite)
