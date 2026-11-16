"""Explain retrieval misses and false positives against labeled queries."""

from __future__ import annotations


def analyze_retrieval_errors(queries, retriever, *, k=10):
    """Return per-query hits, misses, and false positives."""
    analysis = []
    for query in queries:
        relevant = set(query.get('relevant_accesses', query.get('relevant_chunk_ids', [])))
        results = retriever(query)[:k]
        returned = [item['chunk_id'] for item in results]
        analysis.append(
            {
                'term': query['term'],
                'k': k,
                'relevant': sorted(relevant),
                'returned': returned,
                'hits': [chunk_id for chunk_id in returned if chunk_id in relevant],
                'misses': sorted(relevant - set(returned)),
                'false_positives': [chunk_id for chunk_id in returned if chunk_id not in relevant],
            }
        )
    return analysis
