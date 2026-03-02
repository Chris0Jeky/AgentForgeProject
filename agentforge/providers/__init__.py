from .base import Provider
from .codex_cli import CodexCliProvider
from .shell import ShellProvider
from .mock import MockProvider

def get_provider(name: str) -> Provider:
    name = name.lower().strip()
    if name == "codex_cli":
        return CodexCliProvider()
    if name == "shell":
        return ShellProvider()
    if name == "mock":
        return MockProvider()
    raise ValueError(f"Unknown provider: {name}")
