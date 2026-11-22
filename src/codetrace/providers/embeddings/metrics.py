"""Record local model usage without logging queries, excerpts, or vectors."""

from ...request_metrics import request_metrics
from .registry import embedding_adapter


def embed_query(provider, query):
    model = getattr(provider, 'model_id', None)
    if model is None:
        model = getattr(getattr(provider, 'metadata', None), 'model_id', None)
    with request_metrics(
        'embedding_query',
        embedding_adapter(model) if model else None,
        model,
        independent=True,
    ):
        return provider.embed_query(query)


def embed_documents(provider, documents):
    model = provider.metadata.model_id
    with request_metrics(
        'embedding_index',
        embedding_adapter(model),
        model,
        independent=True,
        details={'input_count': len(documents)},
    ):
        return provider.embed_documents(documents)
