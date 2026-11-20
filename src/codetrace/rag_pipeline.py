"""Configurable end-to-end grounded RAG pipeline."""

from __future__ import annotations

from contextlib import nullcontext

from .answering import answer_query
from .context_api import build_context
from .conversation import retrieval_question
from .grounded_prompt import build_grounded_prompt
from .latency import timed
from .request_metrics import request_metrics
from .retrieval import retrieve_scoped
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
    timings=None,
    metrics_source='rag_pipeline',
    history=None,
):
    """Retrieve, build grounded context, and optionally generate an answer."""
    measurement = (
        nullcontext(timings)
        if generation_provider is None
        else request_metrics(
            metrics_source,
            getattr(generation_provider, 'provider', None),
            getattr(generation_provider, 'model', None),
            timings,
        )
    )
    with measurement as timings:
        indexed_chunks = len(index.get('chunks', []))
        index, graph = scope_sources(index, graph, search_filters)
        allowed_chunk_ids = (
            {chunk['id'] for chunk in index.get('chunks', [])}
            if search_filters and search_filters.active
            else None
        )
        search_query = retrieval_question(query, history)
        results = retrieval_results
        if results is None:
            with timed(timings, 'retrieval_seconds'):
                results = retrieve_scoped(
                    index,
                    graph,
                    search_query,
                    config=retrieval_config,
                    semantic_store=semantic_store,
                    provider=embedding_provider,
                    allowed_chunk_ids=allowed_chunk_ids,
                )
        if allowed_chunk_ids is not None:
            results = [result for result in results if result.get('chunk_id') in allowed_chunk_ids]
        with timed(timings, 'context_seconds'):
            context = build_context(
                index,
                graph,
                query,
                results,
                relevant_chunk_ids=relevant_chunk_ids,
                flow_analysis=generation_provider is not None,
                **(context_limits or {}),
            )
            if allowed_chunk_ids is not None:
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
        result = answer_query(
            query,
            context,
            generation_provider,
            allow_remote=allow_remote,
            timings=timings,
            history=history,
        )
        return {'answer': result, 'context': context, 'generated': True}
