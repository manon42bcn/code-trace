"""Build bounded evidence packages for grounded downstream answering."""

from __future__ import annotations


def build_evidence_package(index, graph, chunk_id, *, related_limit=10, max_chars=12000):
    """Assemble one chunk with static relations and explicit uncertainty."""
    chunks = {chunk['id']: chunk for chunk in index.get('chunks', [])}
    chunk = chunks.get(chunk_id)
    if chunk is None:
        raise KeyError(f'unknown chunk: {chunk_id}')
    nodes = {node['id']: node for node in graph.get('nodes', [])}
    symbol_node = next(
        (node_id for node_id, node in nodes.items() if node.get('chunk_id') == chunk_id), None
    )
    relations = []
    for edge in graph.get('edges', []):
        if edge.get('source') == symbol_node or edge.get('target') == symbol_node:
            other_id = (
                edge.get('target') if edge.get('source') == symbol_node else edge.get('source')
            )
            relations.append({'type': edge.get('type'), 'node': nodes.get(other_id, {})})
    relations = sorted(
        relations, key=lambda item: (item['type'] or '', item['node'].get('id', ''))
    )[:related_limit]
    content = chunk.get('content', '')
    citation = {
        'chunk_id': chunk_id,
        'path': chunk.get('path'),
        'symbol': chunk.get('symbol'),
        'start_line': chunk.get('start_line'),
        'end_line': chunk.get('end_line'),
        'evidence_type': 'chunk',
    }
    return {
        'chunk': {
            key: chunk.get(key)
            for key in ('id', 'path', 'language', 'symbol', 'start_line', 'end_line')
        },
        'citation': citation,
        'certainty': 'static_candidate',
        'certainty_taxonomy': [
            'observed_static_fact',
            'static_candidate',
            'ambiguous',
            'not_available',
            'runtime_observed',
        ],
        'content': content[:max_chars],
        'original_content_chars': len(content),
        'content_truncated': len(content) > max_chars,
        'relations': relations,
        'evidence_status': 'static_candidate',
        'runtime_verified': False,
        'limitations': ['static relationships do not prove execution or runtime values'],
    }


def build_multi_chunk_context(
    index,
    graph,
    results,
    *,
    max_chunks=10,
    max_chars=30000,
    max_relations=10,
    max_tokens=None,
    related_limit=10,
    expansion_depth=0,
):
    """Assemble deduplicated, deterministic evidence packages from ranked results."""
    if expansion_depth < 0:
        raise ValueError('expansion_depth must be non-negative')
    selected = []
    retrieved_results = len(results)
    retrieved_unique = len({r.get('chunk_id') for r in results})
    seen = set()
    if expansion_depth:
        nodes = {n.get('id'): n for n in graph.get('nodes', [])}

        frontier = {r.get('chunk_id') for r in results if r.get('chunk_id')}
        expanded = set(frontier)
        for _ in range(expansion_depth):
            next_frontier = set()
            for edge in graph.get('edges', []):
                source = nodes.get(edge.get('source'), {})
                target = nodes.get(edge.get('target'), {})
                if source.get('chunk_id') in frontier and target.get('chunk_id'):
                    next_frontier.add(target['chunk_id'])
            next_frontier -= expanded
            expanded |= next_frontier
            frontier = next_frontier
        results = [
            *results,
            *(
                {'chunk_id': chunk_id, 'score': 0.0, 'source': 'structural-expansion'}
                for chunk_id in sorted(expanded - {r.get('chunk_id') for r in results})
            ),
        ]
    candidates = list({r.get('chunk_id'): None for r in results})
    excluded = {'max_chunks': 0, 'max_chars': 0, 'max_tokens': 0}
    remaining = max_chars
    for result in results:
        chunk_id = result.get('chunk_id')
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        if len(selected) >= max_chunks:
            excluded['max_chunks'] += 1
            continue
        if remaining <= 0:
            excluded['max_chars'] += 1
            continue
        package = build_evidence_package(
            index,
            graph,
            chunk_id,
            related_limit=min(related_limit, max_relations),
            max_chars=remaining,
        )
        content_size = len(package['content'])
        estimated_tokens = (content_size + 3) // 4
        if (
            max_tokens is not None
            and sum((len(item['content']) + 3) // 4 for item in selected) + estimated_tokens
            > max_tokens
        ):
            excluded['max_tokens'] += 1
            continue
        package['retrieval'] = {
            key: result.get(key)
            for key in ('score', 'source', 'sources', 'ranking')
            if result.get(key) is not None
        }
        package['citation']['evidence_type'] = (result.get('access_types') or ['chunk'])[0]
        selected.append(package)
        remaining -= content_size
    return {
        'items': selected,
        'selected_chunks': len(selected),
        'max_chunks': max_chunks,
        'max_chars': max_chars,
        'max_relations': max_relations,
        'max_tokens': max_tokens,
        'content_chars': max_chars - remaining,
        'estimated_tokens': ((max_chars - remaining) + 3) // 4,
        'budget_estimated_tokens': sum((len(item['content']) + 3) // 4 for item in selected),
        'excluded_results': max(0, len(results) - len(selected)),
        'related_limit': min(related_limit, max_relations),
        'expansion_depth': expansion_depth,
        'selection': {
            'retrieved_results': retrieved_results,
            'retrieved_unique_chunks': retrieved_unique,
            'expanded_unique_chunks': len(candidates) - retrieved_unique,
            'candidate_chunks': len(candidates),
            'duplicate_results': len(results) - len(candidates),
            'selected_chunks': len(selected),
            'excluded_chunks': len(candidates) - len(selected),
            'excluded_by_budget': excluded,
            'truncated_chunks': sum(item['content_truncated'] for item in selected),
        },
    }
