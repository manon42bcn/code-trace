"""Two-stage semantic retrieval: precise v1 ranking plus v2 expansion."""

from __future__ import annotations


def two_stage_retrieve(v1_results, v2_results, *, initial_k=5, limit=10, v2_weight=0.25):
    """Keep v1's early precision while allowing v2 to expand the candidate pool."""
    initial = v1_results[:initial_k]
    candidates = {item['chunk_id']: dict(item) for item in initial}
    for item in v2_results:
        current = candidates.get(item['chunk_id'])
        if current is None:
            candidates[item['chunk_id']] = {
                **item,
                'score': item.get('score', 0.0) * v2_weight,
                'source': 'semantic-v2-expansion',
            }
        else:
            current['score'] = current.get('score', 0.0) + item.get('score', 0.0) * v2_weight
            current['source'] = 'semantic-v1-v2'
    return sorted(candidates.values(), key=lambda x: (-x['score'], x['chunk_id']))[:limit]
