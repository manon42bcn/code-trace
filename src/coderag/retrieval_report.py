"""Reproducible JSON reports for retrieval evaluations."""

from __future__ import annotations

import json
from pathlib import Path


def save_retrieval_report(path, *, metadata, evaluation, queries):
    """Persist evaluation metrics, query labels, and run metadata deterministically."""
    payload = {
        'schema_version': 1,
        'metadata': metadata,
        'queries': queries,
        'evaluation': evaluation,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )
    return payload
