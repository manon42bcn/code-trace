"""Attach generic evidence-graph metadata to chunks before embedding."""

from __future__ import annotations


def enrich_chunks_from_graph(index, graph):
    """Return a copy of an index with per-chunk keys, accesses, and relations."""
    chunks = [dict(chunk) for chunk in index.get('chunks', [])]
    nodes = {node['id']: node for node in graph.get('nodes', [])}
    by_chunk = {chunk['id']: chunk for chunk in chunks}
    for edge in graph.get('edges', []):
        source = nodes.get(edge.get('source'), {})
        target = nodes.get(edge.get('target'), {})
        chunk_id = source.get('chunk_id')
        chunk = by_chunk.get(chunk_id)
        if not chunk:
            continue
        relations = set(chunk.get('relations', []))
        relations.add(edge.get('type'))
        chunk['relations'] = sorted(relations - {None})
        if target.get('kind') == 'data_key':
            keys = set(chunk.get('related_keys', []))
            keys.add(target.get('key'))
            chunk['related_keys'] = sorted(keys - {None})
            if edge.get('type') in {'reads', 'writes'}:
                access = set(chunk.get('access_types', []))
                access.add(edge['type'])
                chunk['access_types'] = sorted(access)
    return {**index, 'chunks': chunks}
