"""End-to-end lexical, structural, and semantic retrieval."""

from __future__ import annotations

from .hybrid_search import hybrid_search
from .lexical_search import search_index
from .query_planning import active_sources, plan_query
from .query_routing import classify_query
from .semantic_search import search_vectors
from .structural_search import search_graph
from .two_stage_retrieval import two_stage_retrieve


def search_hybrid(
    index,
    graph,
    term,
    *,
    lexical_kind='any',
    structural_kind='any',
    exact=False,
    limit=50,
    semantic_store=None,
    provider=None,
    intent=None,
    structural_edge_type=None,
    access='all',
    semantic_profile='default',
    semantic_initial_k=1,
    semantic_v2_weight=0.05,
    allowed_chunk_ids=None,
    mode='configured',
):
    if semantic_initial_k < 1:
        raise ValueError('semantic_initial_k must be positive')
    if semantic_v2_weight < 0:
        raise ValueError('semantic_v2_weight must be non-negative')
    if access is None:
        access = 'all'
    if access not in {'all', 'writes', 'reads'}:
        raise ValueError('access must be all, writes, or reads')
    if allowed_chunk_ids is not None:
        index = {
            **index,
            'chunks': [c for c in index.get('chunks', []) if c['id'] in allowed_chunk_ids],
        }
    structural_edge_type = None if access == 'all' else access
    intent = intent or classify_query(term, kind=lexical_kind)
    query_plan = plan_query(term, kind=lexical_kind, exact=exact)
    source_plan = {**query_plan, 'intent': intent}
    sources = active_sources(
        source_plan, mode, semantic_available=bool(semantic_store and provider)
    )
    lexical = (
        search_index(
            index, term, kind=lexical_kind, exact=exact, limit=limit, query_plan=query_plan
        )
        if 'lexical' in sources
        else []
    )
    structural = (
        search_graph(
            graph,
            term,
            kind=structural_kind,
            edge_type=structural_edge_type,
            limit=limit,
            allowed_chunk_ids=allowed_chunk_ids,
        )
        if 'structural' in sources
        else []
    )
    semantic = []

    def semantic_results(store):
        if isinstance(store, list):
            if allowed_chunk_ids is None:
                return store
            return [row for row in store if row.get('chunk_id') in allowed_chunk_ids][:limit]
        return search_vectors(
            store, provider, term, top_k=limit, allowed_chunk_ids=allowed_chunk_ids
        )

    if 'semantic' in sources and semantic_store and provider:
        if semantic_profile == 'two_stage' and isinstance(semantic_store, dict):
            v1 = semantic_store.get('v1')
            v2 = semantic_store.get('v2')
            v1_results = semantic_results(v1)
            v2_results = semantic_results(v2)
            semantic = two_stage_retrieve(
                v1_results,
                v2_results,
                initial_k=semantic_initial_k,
                limit=limit,
                v2_weight=semantic_v2_weight,
            )
        else:
            semantic = search_vectors(
                semantic_store['v1'] if isinstance(semantic_store, dict) else semantic_store,
                provider,
                term,
                top_k=limit,
                allowed_chunk_ids=allowed_chunk_ids,
            )
    return hybrid_search(
        lexical,
        structural,
        semantic,
        access=access,
        limit=limit,
        chunks={chunk['id']: chunk for chunk in index.get('chunks', [])},
        term=term,
        query_plan=query_plan if mode != 'semantic' else None,
    )
