import pytest

from coderag.generation_safety import validate_generation_context


def test_remote_generation_requires_explicit_consent():
    with pytest.raises(PermissionError):
        validate_generation_context({'items': []})


def test_sensitive_paths_are_rejected():
    context = {'items': [{'citation': {'path': 'secrets/.env'}}]}
    with pytest.raises(PermissionError, match='sensitive'):
        validate_generation_context(context, allow_remote=True)
