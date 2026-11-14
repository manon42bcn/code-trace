"""Incremental embedding updates keyed by chunk content and model metadata."""

from __future__ import annotations

from .embedding_text import chunk_embedding_text


def update_embedding_store(index, repository, provider, store):
    """Embed only new or changed chunks and remove deleted chunks."""
    chunks = index.get('chunks', [])
    current = {chunk['id']: chunk for chunk in chunks}
    stale = set(store.records) - set(current)
    for chunk_id in stale:
        del store.records[chunk_id]

    pending = []
    for chunk_id, chunk in current.items():
        text = chunk_embedding_text(
            chunk,
            repository=repository,
            related_keys=chunk.get('related_keys'),
            access_types=chunk.get('access_types'),
            relations=chunk.get('relations'),
        )
        import hashlib

        content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        existing = store.records.get(chunk_id)
        if (
            existing
            and existing.get('content_hash') == content_hash
            and existing.get('embedding_text_version') == provider.metadata.text_version
        ):
            continue
        pending.append((chunk_id, chunk, text, content_hash))

    if pending:
        vectors = provider.embed_documents([item[2] for item in pending])
        store.upsert(
            [
                {
                    'chunk_id': chunk_id,
                    'vector': vector,
                    'content_hash': content_hash,
                    'embedding_text_version': provider.metadata.text_version,
                    'path': chunk.get('path'),
                    'language': chunk.get('language'),
                    'symbol': chunk.get('symbol'),
                }
                for (chunk_id, chunk, _, content_hash), vector in zip(pending, vectors, strict=True)
            ],
            provider.metadata,
        )
    store.save()
    return {'embedded': len(pending), 'reused': len(current) - len(pending), 'deleted': len(stale)}
