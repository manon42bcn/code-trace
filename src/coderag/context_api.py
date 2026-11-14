"""Stable context-building API for downstream grounded generation."""

from __future__ import annotations

from .context_evaluation import evaluate_context_package
from .intent_context import build_context_for_query


def build_context(
    index,
    graph,
    query,
    retrieval_results,
    *,
    intent=None,
    relevant_chunk_ids=None,
    flow_analysis=False,
    **limits,
):
    """Build and optionally evaluate an intent-aware evidence context."""
    package = build_context_for_query(
        index, graph, query, retrieval_results, intent=intent, flow_analysis=flow_analysis, **limits
    )
    package['evaluation'] = (
        evaluate_context_package(package, relevant_chunk_ids)
        if relevant_chunk_ids is not None
        else None
    )
    package['api_version'] = '1'
    return package
