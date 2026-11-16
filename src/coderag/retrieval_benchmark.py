"""Reproducible comparison of retrieval strategies."""

from __future__ import annotations

import time

from .evaluation import evaluate_retrieval


def benchmark_retrievers(queries, retrievers, *, k_values=(1, 5, 10)):
    """Evaluate named retrievers and record elapsed wall-clock time."""
    report = {'queries': len(queries), 'strategies': {}}
    for name, retriever in retrievers.items():
        started = time.perf_counter()
        metrics = evaluate_retrieval(queries, retriever, k_values=k_values)
        report['strategies'][name] = {
            **metrics,
            'elapsed_seconds': time.perf_counter() - started,
        }
    return report
