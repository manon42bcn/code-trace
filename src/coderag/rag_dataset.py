"""Versioned datasets for reproducible RAG evaluation."""

from __future__ import annotations

import json
from pathlib import Path


def load_rag_dataset(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise ValueError('RAG dataset must be a list')
    for item in data:
        if not item.get('query') or 'relevant_citations' not in item:
            raise ValueError('each RAG item requires query and relevant_citations')
    return data
