"""Semantic retrieval over the provider-neutral local vector store."""

from __future__ import annotations

from .providers.embeddings.metrics import embed_query


def search_vectors(
    store, provider, query, *, top_k=10, filters=None, allowed_chunk_ids=None, query_vector=None
):
    """Embed a query locally and return normalized semantic results."""
    if allowed_chunk_ids is not None and not allowed_chunk_ids:
        return []
    vector = embed_query(provider, query) if query_vector is None else query_vector
    options = {'allowed_chunk_ids': allowed_chunk_ids} if allowed_chunk_ids is not None else {}
    results = store.search(vector, top_k=top_k, filters=filters, **options)
    return [
        {
            'chunk_id': result['chunk_id'],
            'score': result['score'],
            'source': 'semantic',
            'path': result.get('path'),
            'language': result.get('language'),
            'symbol': result.get('symbol'),
        }
        for result in results
    ]
