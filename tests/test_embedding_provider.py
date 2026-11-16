import pytest

from coderag.embedding_provider import SentenceTransformerProvider


def test_provider_reports_missing_optional_dependency(monkeypatch):
    real_import = __import__

    def missing(name, *args, **kwargs):
        if name == 'sentence_transformers':
            raise ImportError('missing')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr('builtins.__import__', missing)
    with pytest.raises(RuntimeError, match='sentence-transformers'):
        SentenceTransformerProvider()
