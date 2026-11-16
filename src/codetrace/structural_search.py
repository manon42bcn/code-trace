"""Structural retrieval over the static evidence graph."""

from __future__ import annotations

from .match_ranking import describe_match, rank_key


def search_graph(graph, term, *, kind='any', edge_type=None, limit=50, allowed_chunk_ids=None):
    """Find graph nodes by attribute and optionally filter data-key edges."""
    allowed = {'any', 'symbol', 'path', 'key'}
    if kind not in allowed:
        raise ValueError('kind must be any, symbol, path, key, or any')
    results = []
    nodes = {node['id']: node for node in graph.get('nodes', [])}
    incoming = {}
    for edge in graph.get('edges', []):
        incoming.setdefault(edge.get('target'), []).append(edge)
    for node in graph.get('nodes', []):
        fields = {'symbol': node.get('symbol'), 'path': node.get('path'), 'key': node.get('key')}
        matched = [
            field
            for field, value in fields.items()
            if value is not None and (kind == 'any' or field == kind) and term in str(value)
        ]
        if matched:
            result = {
                'node_id': node['id'],
                'score': 1.0,
                'match_kinds': matched,
                'ranking': describe_match(node, term),
                **{k: fields[k] for k in matched},
            }
            if node.get('chunk_id') is not None:
                result['chunk_id'] = node['chunk_id']
            linked_chunks = []
            accesses = []
            if node.get('kind') == 'data_key':
                for edge in incoming.get(node['id'], []):
                    if edge_type and edge.get('type') != edge_type:
                        continue
                    source = nodes.get(edge.get('source'), {})
                    if source.get('chunk_id') is not None and (
                        allowed_chunk_ids is None or source['chunk_id'] in allowed_chunk_ids
                    ):
                        chunk_id = source['chunk_id']
                        linked_chunks.append(chunk_id)
                        accesses.append({'chunk_id': chunk_id, 'edge_type': edge.get('type')})
            if linked_chunks:
                result['accesses'] = sorted(
                    accesses, key=lambda item: (item['chunk_id'], item['edge_type'])
                )
                result['access_types'] = sorted({item['edge_type'] for item in accesses})
                result['score'] = 1.0 if edge_type else 0.8
                result['chunk_ids'] = sorted(set(linked_chunks))
                result['chunk_id'] = result['chunk_ids'][0]
            if allowed_chunk_ids is not None and result.get('chunk_id') not in allowed_chunk_ids:
                continue
            results.append(result)
    results.sort(key=lambda item: rank_key(item, identity='node_id'))
    return results[:limit]
