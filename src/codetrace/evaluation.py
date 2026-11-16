"""Provider-neutral retrieval metrics and labeled evaluation."""

from __future__ import annotations


def recall_at_k(results, relevant, k):
    found = {item['chunk_id'] for item in results[:k]}
    return len(found & set(relevant)) / len(set(relevant)) if relevant else 1.0


def precision_at_k(results, relevant, k):
    found = {item['chunk_id'] for item in results[:k]}
    return len(found & set(relevant)) / min(k, len(results)) if results else 0.0


def mrr(results, relevant):
    relevant = set(relevant)
    for rank, item in enumerate(results, 1):
        if item['chunk_id'] in relevant:
            return 1 / rank
    return 0.0


def relevant_for(query, *, edge_type=None):
    if edge_type == 'writes' and 'relevant_writers' in query:
        return query['relevant_writers']
    if edge_type == 'reads' and 'relevant_readers' in query:
        return query['relevant_readers']
    if 'relevant_accesses' in query:
        return query['relevant_accesses']
    return query.get('relevant_chunk_ids', set())


def evaluate_retrieval(queries, retriever, *, k_values=(1, 5, 10), edge_type=None):
    """Evaluate labeled queries, optionally selecting writer/reader labels."""
    if not queries:
        return {'queries': 0, 'metrics': {}}
    rows = []
    for query in queries:
        results = retriever(query)
        relevant = relevant_for(query, edge_type=edge_type)
        rows.append(
            {
                'mrr': mrr(results, relevant),
                'recall': {k: recall_at_k(results, relevant, k) for k in k_values},
                'precision': {k: precision_at_k(results, relevant, k) for k in k_values},
            }
        )
    return {
        'queries': len(rows),
        'metrics': {
            'mrr': sum(row['mrr'] for row in rows) / len(rows),
            'recall': {k: sum(row['recall'][k] for row in rows) / len(rows) for k in k_values},
            'precision': {
                k: sum(row['precision'][k] for row in rows) / len(rows) for k in k_values
            },
        },
    }
