import pytest

from codetrace.embedding_provider import SentenceTransformerProvider


def test_provider_reports_missing_optional_dependency(monkeypatch):
    real_import = __import__

    def missing(name, *args, **kwargs):
        if name == 'sentence_transformers':
            raise ImportError('missing')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr('builtins.__import__', missing)
    with pytest.raises(RuntimeError, match='sentence-transformers'):
        SentenceTransformerProvider()


def test_mlx_groups_similar_lengths_and_restores_input_order(monkeypatch):
    from types import SimpleNamespace

    from codetrace.providers.embeddings import mlx

    batches = []

    class Model:
        def encode(self, texts, _tokenizer, **_kwargs):
            batches.append(texts)
            return SimpleNamespace(
                tolist=lambda: [[float(len(text))] * mlx.DIMENSIONS for text in texts]
            )

    monkeypatch.setattr(mlx, 'BATCH_SIZE', 2)
    provider = mlx.MLXJinaProvider('mlx:/fixture')
    provider._loaded = (Model(), None)
    vectors = provider.embed_documents(['longest', 'x', 'four', 'yy'])

    assert batches == [['x', 'yy'], ['four', 'longest']]
    assert [vector[0] for vector in vectors] == [7.0, 1.0, 4.0, 2.0]
