"""Deterministic reciprocal-rank fusion for retrieval sources."""

from __future__ import annotations


def reciprocal_rank_fusion(result_sets, *, k=60, limit=50):
    """Fuse ranked result lists without assuming comparable score scales."""
    merged = {}
    for source, results in result_sets.items():
        for rank, result in enumerate(results, 1):
            chunk_id = result.get('chunk_id', result.get('node_id'))
            if chunk_id is None:
                continue
            item = merged.setdefault(
                chunk_id, {'chunk_id': chunk_id, 'score': 0.0, 'sources': [], 'match_kinds': []}
            )
            item['score'] += 1 / (k + rank)
            item['sources'] = sorted(set(item['sources']) | {source})
            item['match_kinds'] = sorted(
                set(item['match_kinds']) | set(result.get('match_kinds', []))
            )
            for field in ('path', 'symbol', 'language'):
                if field not in item and result.get(field) is not None:
                    item[field] = result[field]
    for item in merged.values():
        item['source'] = 'hybrid' if len(item['sources']) > 1 else item['sources'][0]
    return sorted(merged.values(), key=lambda item: (-item['score'], item['chunk_id']))[:limit]
