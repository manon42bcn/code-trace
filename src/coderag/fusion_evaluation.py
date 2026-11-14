"""Evaluate configurable semantic representation fusion."""

from __future__ import annotations

from .embedding_fusion import fuse_embedding_results
from .evaluation import evaluate_retrieval


def evaluate_fusion_weights(queries, result_sets, weight_configs, *, k_values=(1, 5, 10)):
    """Compare named v1/v2 weight configurations."""
    report = {}
    for name, weights in weight_configs.items():

        def retrieve(query, weights=weights):
            return fuse_embedding_results(
                result_sets[query['term']], weights=weights, limit=max(k_values)
            )

        report[name] = {
            'weights': weights,
            **evaluate_retrieval(queries, retrieve, k_values=k_values),
        }
    return report
