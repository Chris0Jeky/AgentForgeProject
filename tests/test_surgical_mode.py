from __future__ import annotations

from agentforge.core.runner import _status_changed_paths_from_porcelain, _violating_paths


def test_status_changed_paths_from_porcelain_parses_common_entries() -> None:
    porcelain = "\n".join(
        [
            " M agentforge/core/runner.py",
            "?? docs/codex-smoke.md",
            "R  old/path.txt -> new/path.txt",
            "",
        ]
    )
    got = _status_changed_paths_from_porcelain(porcelain)
    assert got == [
        "agentforge/core/runner.py",
        "docs/codex-smoke.md",
        "new/path.txt",
    ]


def test_violating_paths_reports_only_out_of_scope() -> None:
    changed = [
        "docs/codex-smoke.md",
        "docs/notes.md",
        "agentforge/core/runner.py",
    ]
    allowed = ["docs/codex-smoke.md", "docs/notes.md"]
    bad = _violating_paths(changed, allowed)
    assert bad == ["agentforge/core/runner.py"]

