"""Deterministic exact lexical retrieval over a CodeTrace index."""

from __future__ import annotations

from .match_ranking import describe_match, rank_key


def search_index(index, term, *, kind='any', exact=False, limit=50, query_plan=None):
    """Return chunk matches classified by symbol, path, and content."""
    if kind not in {'any', 'symbol', 'path', 'content'}:
        raise ValueError('kind must be any, symbol, path, or content')
    if limit < 0:
        raise ValueError('limit must be non-negative')
    if query_plan and query_plan['lexical_mode'] == 'token_overlap':
        from .natural_search import search_natural

        return search_natural(index, query_plan, kind=kind, limit=limit)
    kinds = ('symbol', 'path', 'content') if kind == 'any' else (kind,)
    results = []
    for chunk in index.get('chunks', []):
        matched = []
        lines = []
        for field in kinds:
            value = chunk.get(field, '') or ''
            if value == term if exact else term in value:
                matched.append(field)
            if field == 'content':
                for offset, line in enumerate(value.splitlines()):
                    hit = line == term if exact else term in line
                    if hit:
                        lines.append({'line': chunk.get('start_line', 1) + offset, 'text': line})
        if matched:
            scores = {'symbol': 1.0, 'path': 0.9, 'content': 0.8}
            result = {
                'chunk_id': chunk['id'],
                'score': max(scores[k] for k in matched),
                'match_kinds': matched,
                'path': chunk.get('path'),
                'symbol': chunk.get('symbol'),
                'start_line': chunk.get('start_line'),
                'ranking': describe_match(chunk, term),
            }
            if lines:
                result['matching_lines'] = lines
            results.append(result)
    results.sort(key=rank_key)
    return results[:limit]
