"""Run and aggregate reproducible RAG dataset evaluations."""

from __future__ import annotations

from statistics import median, quantiles

from .generation import GenerationResult
from .latency import timed
from .rag_evaluation import evaluate_answer


def evaluate_rag_dataset(dataset, answer_runner, *, include_queries=True):
    """Run labeled queries through an answer runner and aggregate metrics."""
    rows = []
    for case_number, item in enumerate(dataset, start=1):
        row = {'case': case_number, 'timings': {}}
        if include_queries:
            row['query'] = item['query']
        rows.append(row)
        try:
            with timed(row['timings'], 'total_seconds'):
                result = answer_runner(item['query'])
        except Exception as exc:
            row['error_type'] = type(exc).__name__
            continue
        row['timings'].update(result.get('timings', {}))
        answer = result.get('answer')
        if not isinstance(answer, GenerationResult):
            row['error_type'] = 'NoGeneratedAnswer'
            continue
        row['metrics'] = evaluate_answer(
            answer,
            relevant_citations=item['relevant_citations'],
            required_claims=item.get('required_claims', 0),
        )

    evaluated = [row['metrics'] for row in rows if 'metrics' in row]
    latency = {}
    for name in (
        'total_seconds',
        'retrieval_seconds',
        'context_seconds',
        'generation_seconds',
        'validation_seconds',
    ):
        samples = [
            row['timings'][name] for row in rows if 'metrics' in row and name in row['timings']
        ]
        if samples:
            latency[name] = {
                'samples': len(samples),
                'median': median(samples),
                'p95': quantiles(samples, n=100, method='inclusive')[94]
                if len(samples) >= 20
                else None,
            }
    failures = len(rows) - len(evaluated)
    return {
        'queries': len(rows),
        'rows': rows,
        'failures': failures,
        'error_rate': failures / len(rows) if rows else 0.0,
        'latency': latency,
        'citation_recall': sum(metrics['citation_recall'] for metrics in evaluated) / len(evaluated)
        if evaluated
        else 0.0,
        'claim_coverage': sum(metrics['claim_coverage'] for metrics in evaluated) / len(evaluated)
        if evaluated
        else 0.0,
        'invalid_citations': sum(metrics['invalid_citations'] for metrics in evaluated),
    }
