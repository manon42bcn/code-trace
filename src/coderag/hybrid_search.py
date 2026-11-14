"""Small deterministic fusion of lexical and structural retrieval."""

from __future__ import annotations

from .match_ranking import describe_match, rank_key


def hybrid_search(
    lexical_results,
    structural_results,
    semantic_results=None,
    *,
    access='all',
    limit=50,
    chunks=None,
    term=None,
    query_plan=None,
):
    """Merge retrieval sources, prioritizing the requested access profile."""
    if access not in {'all', 'writes', 'reads'}:
        raise ValueError('access must be all, writes, or reads')
    merged = {}
    for source, results in (
        ('lexical', lexical_results),
        ('structural', structural_results),
        ('semantic', semantic_results or []),
    ):
        for result in results:
            chunk_ids = result.get('chunk_ids') or [result.get('chunk_id', result.get('node_id'))]
            chunk_ids = [chunk_id for chunk_id in chunk_ids if chunk_id is not None]
            for chunk_id in chunk_ids:
                item = dict(result)
                item['chunk_id'] = chunk_id
                item['source'] = source
                chunk = (chunks or {}).get(chunk_id)
                if chunk is not None:
                    for field in ('path', 'symbol', 'start_line'):
                        item[field] = chunk.get(field)
                    if term is not None:
                        if query_plan and query_plan['lexical_mode'] == 'token_overlap':
                            from .natural_search import natural_signal

                            signal = natural_signal(chunk, query_plan)
                        else:
                            signal = describe_match(chunk, term)
                        if (
                            not item.get('ranking')
                            or signal['priority'] < item['ranking']['priority']
                        ):
                            item['ranking'] = signal
                if result.get('accesses'):
                    item['access_types'] = sorted(
                        {
                            access['edge_type']
                            for access in result['accesses']
                            if access['chunk_id'] == chunk_id
                        }
                    )
                if item.get('node_id'):
                    item['structural_node_ids'] = [item['node_id']]
                if chunk_id in merged:
                    current = merged[chunk_id]
                    sources = set(current.get('sources', [current['source']])) | {source}
                    if item.get('access_types'):
                        current['access_types'] = sorted(
                            set(current.get('access_types', [])) | set(item['access_types'])
                        )
                    if item.get('node_id'):
                        current['structural_node_ids'] = sorted(
                            set(current.get('structural_node_ids', [])) | {item['node_id']}
                        )
                    incoming_rank = (item.get('ranking') or {}).get('priority', 5)
                    current_rank = (current.get('ranking') or {}).get('priority', 5)
                    if incoming_rank < current_rank:
                        current['ranking'] = item['ranking']
                    current['source'] = 'hybrid'
                    current['sources'] = sorted(sources)
                    current['score'] = max(current['score'], item.get('score', 0.0))
                    current['match_kinds'] = sorted(
                        set(current.get('match_kinds', [])) | set(item.get('match_kinds', []))
                    )
                else:
                    merged[chunk_id] = item

    def rank(item):
        access_match = bool(access != 'all' and access in item.get('access_types', []))
        return (0 if access_match else 1, *rank_key(item))

    return sorted(merged.values(), key=rank)[:limit]
