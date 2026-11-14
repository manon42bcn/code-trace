"""Configurable end-to-end grounded RAG pipeline."""

from __future__ import annotations

from .answering import answer_query
from .context_api import build_context
from .grounded_prompt import build_grounded_prompt
from .retrieval import RetrievalConfig, retrieve
from .source_filters import scope_sources


def answer(
    query,
    *,
    index,
    graph,
    retrieval_results=None,
    retrieval_config=None,
    generation_provider=None,
    relevant_chunk_ids=None,
    allow_remote=False,
    semantic_store=None,
    embedding_provider=None,
    context_limits=None,
    search_filters=None,
):
    """Retrieve, build grounded context, and optionally generate an answer."""
    indexed_chunks = len(index.get('chunks', []))
    index, graph = scope_sources(index, graph, search_filters)
    config = retrieval_config or RetrievalConfig()
    results = retrieval_results
    if results is None:
        results = retrieve(
            index,
            graph,
            query,
            config=config,
            semantic_store=semantic_store,
            provider=embedding_provider,
            filters=search_filters,
        )
    if search_filters and search_filters.active:
        allowed = {chunk['id'] for chunk in index.get('chunks', [])}
        results = [result for result in results if result.get('chunk_id') in allowed]
    context = build_context(
        index,
        graph,
        query,
        results,
        relevant_chunk_ids=relevant_chunk_ids,
        flow_analysis=generation_provider is not None,
        **(context_limits or {}),
    )
    if search_filters and search_filters.active:
        context['source_scope'] = {
            'filters': search_filters.describe(),
            'indexed_chunks': indexed_chunks,
            'eligible_chunks': len(index.get('chunks', [])),
        }
    if generation_provider is None:
        return {
            'answer': None,
            'context': context,
            'prompt': build_grounded_prompt(query, context),
            'generated': False,
        }
    result = answer_query(query, context, generation_provider, allow_remote=allow_remote)
    return {'answer': result, 'context': context, 'generated': True}
