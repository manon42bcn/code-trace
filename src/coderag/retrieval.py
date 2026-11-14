"""Configured end-to-end retrieval profile."""

from __future__ import annotations

from dataclasses import dataclass

from .search import search_hybrid
from .source_filters import scope_sources


@dataclass(frozen=True)
class RetrievalConfig:
    lexical_kind: str = 'any'
    structural_kind: str = 'any'
    access: str = 'all'
    semantic_profile: str = 'default'
    semantic_initial_k: int = 1
    semantic_v2_weight: float = 0.05
    limit: int = 50
    mode: str = 'configured'

    @classmethod
    def from_mapping(cls, value=None):
        return cls(**(value or {}))

    def __post_init__(self):
        if self.mode not in {'configured', 'lexical', 'semantic'}:
            raise ValueError('retrieval mode must be configured, lexical or semantic')
        if self.semantic_initial_k < 1 or self.semantic_v2_weight < 0:
            raise ValueError('invalid semantic retrieval configuration')
        if self.limit < 1:
            raise ValueError('limit must be positive')


def retrieve(
    index,
    graph,
    term,
    *,
    config=None,
    exact=False,
    semantic_store=None,
    provider=None,
    filters=None,
):
    """Run the configured lexical/structural/semantic retrieval pipeline."""
    config = config or RetrievalConfig()
    index, graph = scope_sources(index, graph, filters)
    allowed = (
        {chunk['id'] for chunk in index.get('chunks', [])} if filters and filters.active else None
    )
    return search_hybrid(
        index,
        graph,
        term,
        lexical_kind=config.lexical_kind,
        structural_kind=config.structural_kind,
        access=config.access,
        semantic_profile=config.semantic_profile,
        semantic_initial_k=config.semantic_initial_k,
        semantic_v2_weight=config.semantic_v2_weight,
        exact=exact,
        limit=config.limit,
        semantic_store=semantic_store,
        provider=provider,
        allowed_chunk_ids=allowed,
        mode=config.mode,
    )
