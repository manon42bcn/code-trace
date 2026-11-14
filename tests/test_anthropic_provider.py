import builtins

import pytest

from coderag.anthropic_provider import AnthropicProvider


def test_missing_optional_anthropic_dependency(monkeypatch):
    real_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == 'anthropic':
            raise ImportError
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', missing)
    with pytest.raises(RuntimeError, match='anthropic'):
        AnthropicProvider()
