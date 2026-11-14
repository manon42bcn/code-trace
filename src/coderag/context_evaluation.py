"""Evaluation metrics for evidence context packages."""

from __future__ import annotations


def evaluate_context_package(package, relevant_chunk_ids):
    """Measure coverage, redundancy, and budget use for a context package."""
    relevant = set(relevant_chunk_ids)
    items = package.get('items', [])
    ids = [item.get('chunk', {}).get('id') for item in items]
    selected = set(ids)
    return {
        'selected_chunks': len(ids),
        'unique_chunks': len(selected),
        'relevant_chunks': len(selected & relevant),
        'coverage': len(selected & relevant) / len(relevant) if relevant else 1.0,
        'redundancy': 1 - len(selected) / len(ids) if ids else 0.0,
        'truncated_items': sum(item.get('content_truncated', False) for item in items),
        'estimated_tokens': package.get('estimated_tokens', 0),
    }
