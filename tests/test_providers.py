import pytest

from agentforge.providers import get_provider
from agentforge.providers.codex_cli import CodexCliProvider
from agentforge.providers.mock import MockProvider
from agentforge.providers.shell import ShellProvider


def test_get_provider_known_types() -> None:
    assert isinstance(get_provider("codex_cli"), CodexCliProvider)
    assert isinstance(get_provider("shell"), ShellProvider)
    assert isinstance(get_provider("mock"), MockProvider)


def test_get_provider_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_provider("unknown-provider")
