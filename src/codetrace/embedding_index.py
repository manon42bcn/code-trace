"""Incremental embedding updates keyed by chunk content and model metadata."""

from __future__ import annotations

import hashlib

from .embedding_text import chunk_embedding_text
from .providers.embeddings.metrics import embed_documents

BATCH_SIZE = 128


def update_embedding_store(index, repository, provider, store, *, reusable=None, progress=None):
    """Embed only new or changed chunks and remove deleted chunks."""
    chunks = index.get('chunks', [])
    current = {chunk['id']: chunk for chunk in chunks}
    stale = set(store.records) - set(current)
    for chunk_id in stale:
        del store.records[chunk_id]

    pending = []
    reusable = {} if reusable is None else reusable
    for chunk_id, chunk in current.items():
        text = chunk_embedding_text(
            chunk,
            repository=repository,
            related_keys=chunk.get('related_keys'),
            access_types=chunk.get('access_types'),
            relations=chunk.get('relations'),
        )
        content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        existing = store.records.get(chunk_id)
        if (
            existing
            and existing.get('content_hash') == content_hash
            and existing.get('embedding_text_version') == provider.metadata.text_version
        ):
            continue
        previous = reusable.get(chunk_id)
        if (
            previous
            and previous.get('content_hash') == content_hash
            and previous.get('embedding_text_version') == provider.metadata.text_version
        ):
            store.upsert(
                [_record(chunk_id, chunk, content_hash, previous['vector'], provider.metadata)],
                provider.metadata,
            )
        else:
            pending.append((chunk_id, chunk, text, content_hash))

    total = len(pending)
    reused = len(current) - total
    if progress:
        progress(0, total, reused)
    for start in range(0, total, BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        vectors = embed_documents(provider, [item[2] for item in batch])
        store.upsert(
            [
                _record(chunk_id, chunk, content_hash, vector, provider.metadata)
                for (chunk_id, chunk, _, content_hash), vector in zip(batch, vectors, strict=True)
            ],
            provider.metadata,
        )
        if progress:
            progress(start + len(batch), total, reused)
    store.save()
    return {'embedded': total, 'reused': reused, 'deleted': len(stale)}


def _record(chunk_id, chunk, content_hash, vector, metadata):
    return {
        'chunk_id': chunk_id,
        'vector': vector,
        'content_hash': content_hash,
        'embedding_text_version': metadata.text_version,
        'path': chunk.get('path'),
        'language': chunk.get('language'),
        'symbol': chunk.get('symbol'),
    }
