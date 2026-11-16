"""Persist reproducible RAG evaluation reports."""

from __future__ import annotations

import json
from pathlib import Path


def save_rag_report(
    path,
    *,
    query,
    retrieval_config,
    generation_config,
    context_metrics,
    answer_metrics,
    metadata=None,
):
    payload = {
        'schema_version': 1,
        'query': query,
        'retrieval_config': retrieval_config,
        'generation_config': generation_config,
        'context_metrics': context_metrics,
        'answer_metrics': answer_metrics,
        'metadata': metadata or {},
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )
    return payload
