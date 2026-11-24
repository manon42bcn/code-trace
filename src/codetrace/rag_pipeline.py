"""Configurable end-to-end grounded RAG pipeline."""

from __future__ import annotations

from contextlib import nullcontext

from .answering import answer_query
from .context_api import build_context
from .conversation import retrieval_question
from .direct_definition import DIRECT_DEFINITION, direct_definition
from .generation import INSUFFICIENT_EVIDENCE, GenerationResult
from .grounded_prompt import build_grounded_prompt, response_language_instruction
from .latency import timed
from .request_metrics import request_metrics
from .retrieval import retrieve_scoped
from .source_filters import scope_sources
from .sqlite_index import index_backend


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
    prefer_direct=False,
):
    """Retrieve, build grounded context, and optionally generate an answer."""
    details = {'index_backend': index_backend(index)}
    measurement = (
        nullcontext(timings)
        if generation_provider is None
        else request_metrics(
            metrics_source,
            getattr(generation_provider, 'provider', None),
            getattr(generation_provider, 'model', None),
            timings,
            details=details,
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
        scope = (
            {
                'filters': search_filters.describe(),
                'indexed_chunks': indexed_chunks,
                'eligible_chunks': len(index.get('chunks', [])),
            }
            if allowed_chunk_ids is not None
            else None
        )
        if prefer_direct and generation_provider is not None and retrieval_results is None:
            with timed(timings, 'definition_lookup_seconds'):
                direct = direct_definition(
                    query,
                    index,
                    graph,
                    history=history,
                    limits=context_limits,
                    relevant_chunk_ids=relevant_chunk_ids,
                )
            if direct is not None:
                if scope is not None:
                    direct['context']['source_scope'] = scope
                details['answer_mode'] = DIRECT_DEFINITION
                return direct
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
            if scope is not None:
                context['source_scope'] = scope
        if generation_provider is None:
            return {
                'answer': None,
                'context': context,
                'prompt': build_grounded_prompt(query, context),
                'generated': False,
            }
        if prefer_direct and semantic_store and not context['items']:
            spanish = response_language_instruction(query).startswith('Response language: Spanish')
            message = (
                'No encontré evidencia suficiente en el repositorio seleccionado para responder.'
                if spanish
                else 'I found insufficient evidence in the selected repository to answer.'
            )
            details['answer_mode'] = INSUFFICIENT_EVIDENCE
            return {
                'answer': GenerationResult(message, 'codetrace', 'static-index', refusal=True),
                'context': context,
                'generated': False,
                'answer_mode': INSUFFICIENT_EVIDENCE,
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
