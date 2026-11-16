"""Intent-aware evidence context construction."""

from __future__ import annotations

from .code_flow import flow_candidates, is_flow_query, selected_flow
from .evidence_context import build_multi_chunk_context
from .query_routing import classify_query


def build_context_for_query(
    index, graph, query, results, *, intent=None, flow_analysis=False, **limits
):
    """Select structural expansion defaults from generic query intent."""
    flow = None
    if flow_analysis and is_flow_query(query):
        results, flow = flow_candidates(index, graph, query, results)
    intent = intent or ('code_flow' if flow is not None else classify_query(query))
    if intent == 'exact_symbol':
        limits.setdefault('expansion_depth', 1)
    elif intent == 'storage_key':
        limits.setdefault('expansion_depth', 1)
        limits.setdefault('related_limit', 20)
    elif intent == 'structural_relation':
        limits.setdefault('expansion_depth', 2)
    else:
        limits.setdefault('expansion_depth', 0)
    context = build_multi_chunk_context(index, graph, results, **limits)
    if flow is not None:
        context['code_flow'] = selected_flow(flow, context)
    context['query'] = query
    context['intent'] = intent
    return context
