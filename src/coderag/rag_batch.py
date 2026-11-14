"""Run and aggregate reproducible RAG dataset evaluations."""

from __future__ import annotations

from .rag_evaluation import evaluate_answer


def evaluate_rag_dataset(dataset, answer_runner):
    """Run labeled queries through an answer runner and aggregate metrics."""
    rows = []
    for item in dataset:
        result = answer_runner(item['query'])
        answer = result.get('answer')
        metrics = evaluate_answer(
            answer,
            relevant_citations=item['relevant_citations'],
            required_claims=item.get('required_claims', 0),
        )
        rows.append({'query': item['query'], 'metrics': metrics})
    return {
        'queries': len(rows),
        'rows': rows,
        'citation_recall': sum(row['metrics']['citation_recall'] for row in rows) / len(rows)
        if rows
        else 0.0,
        'claim_coverage': sum(row['metrics']['claim_coverage'] for row in rows) / len(rows)
        if rows
        else 0.0,
        'invalid_citations': sum(row['metrics']['invalid_citations'] for row in rows),
    }
