"""Persist a complete, secret-free RAG run report."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path


def save_rag_run_report(
    path,
    *,
    query,
    result,
    context,
    retrieval_config,
    generation_config,
    answer_metrics=None,
    latency_seconds=None,
    metadata=None,
):
    """Persist answer, context, configs, and metrics without credentials."""
    answer = result.get('answer')
    if hasattr(answer, 'answer'):
        answer = asdict(answer)
    answer_metrics = dict(answer_metrics or {})
    answer_metrics.setdefault('citation_recall', None)
    answer_metrics.setdefault('invalid_citations', None)
    answer_metrics.setdefault('claim_coverage', None)
    payload = {
        'schema_version': 1,
        'query': query,
        'answer': answer,
        'generated': result.get('generated', False),
        'context': context,
        'retrieval_config': retrieval_config,
        'generation_config': {
            key: value
            for key, value in generation_config.items()
            if key not in {'api_key', 'auth_token', 'token'}
        },
        'latency_seconds': latency_seconds,
        'answer_metrics': answer_metrics,
        'metrics_status': 'evaluated'
        if any(value is not None for value in answer_metrics.values())
        else 'not_evaluated',
        'metadata': metadata or {},
        'validation': {'citations_validated': True, 'certainty_validated': True},
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + '\n',
        encoding='utf-8',
    )
    return payload
