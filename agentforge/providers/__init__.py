from __future__ import annotations

from importlib import metadata
from typing import Callable, Dict

from .base import Provider
from .codex_cli import CodexCliProvider
from .shell import ShellProvider
from .mock import MockProvider

_BUILTINS = {
    "codex_cli": CodexCliProvider,
    "shell": ShellProvider,
    "mock": MockProvider,
}

def _load_entrypoints() -> Dict[str, Callable[[], Provider]]:
    eps: Dict[str, Callable[[], Provider]] = {}
    try:
        group = "agentforge.providers"
        for ep in metadata.entry_points().select(group=group):
            # Entry point should resolve to a callable returning a Provider instance,
            # or to a Provider class (callable).
            obj = ep.load()
            if callable(obj):
                eps[ep.name] = obj  # type: ignore
    except Exception:
        return {}
    return eps

def get_provider(name: str) -> Provider:
    name = name.lower().strip()
    if name in _BUILTINS:
        return _BUILTINS[name]()
    eps = _load_entrypoints()
    if name in eps:
        obj = eps[name]
        inst = obj()
        return inst  # type: ignore
    raise ValueError(f"Unknown provider: {name}")
