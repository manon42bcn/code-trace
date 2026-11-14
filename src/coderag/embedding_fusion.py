"""Configurable fusion of semantic retrieval representations."""

from __future__ import annotations


def fuse_embedding_results(result_sets, *, weights=None, limit=50):
    """Fuse ranked results from representation versions by weighted score."""
    weights = weights or dict.fromkeys(result_sets, 1.0)
    merged = {}
    for name, results in result_sets.items():
        weight = weights.get(name, 1.0)
        for _rank, result in enumerate(results, 1):
            chunk_id = result['chunk_id']
            item = merged.setdefault(chunk_id, {'chunk_id': chunk_id, 'score': 0.0, 'sources': []})
            item['score'] += weight * result.get('score', 0.0)
            item['sources'] = sorted(set(item['sources']) | {name})
            for field in ('path', 'language', 'symbol'):
                if field not in item and result.get(field) is not None:
                    item[field] = result[field]
    for item in merged.values():
        item['source'] = 'semantic-fusion' if len(item['sources']) > 1 else item['sources'][0]
    return sorted(merged.values(), key=lambda x: (-x['score'], x['chunk_id']))[:limit]
