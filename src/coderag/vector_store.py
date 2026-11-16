"""Small local JSON vector store with version compatibility checks."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .embeddings import EmbeddingMetadata, validate_vectors


class VectorStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.metadata: EmbeddingMetadata | None = None
        self.records: dict[str, dict] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self.metadata = EmbeddingMetadata(**data['metadata'])
            self.records = data.get('records', {})

    def upsert(self, records: list[dict], metadata: EmbeddingMetadata) -> None:
        vectors = [record['vector'] for record in records]
        validate_vectors(vectors, metadata)
        if self.metadata and self.metadata != metadata:
            raise ValueError('vector store metadata is incompatible')
        self.metadata = metadata
        for record in records:
            self.records[record['chunk_id']] = dict(record)

    def delete_missing(self, chunk_ids: set[str]) -> None:
        self.records = {key: value for key, value in self.records.items() if key in chunk_ids}

    def save(self) -> None:
        if self.metadata is None:
            raise ValueError('cannot save an empty vector store without metadata')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {'schema_version': 1, 'metadata': self.metadata.__dict__, 'records': self.records}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    def search(
        self,
        query: list[float],
        *,
        top_k: int = 10,
        filters: dict | None = None,
        allowed_chunk_ids: set[str] | None = None,
    ) -> list[dict]:
        if self.metadata is None:
            return []
        validate_vectors([query], self.metadata)
        filters = filters or {}
        query_norm = math.sqrt(sum(value * value for value in query))
        if not query_norm:
            return []
        results = []
        for record in self.records.values():
            if allowed_chunk_ids is not None and record.get('chunk_id') not in allowed_chunk_ids:
                continue
            if any(record.get(key) != value for key, value in filters.items()):
                continue
            vector = record['vector']
            norm = math.sqrt(sum(value * value for value in vector))
            score = (
                sum(a * b for a, b in zip(query, vector, strict=True)) / (query_norm * norm)
                if norm
                else 0.0
            )
            results.append({**record, 'score': score})
        return sorted(results, key=lambda item: (-item['score'], item['chunk_id']))[:top_k]
