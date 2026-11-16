"""Context budget configuration parsing."""

from __future__ import annotations


def context_limits_from_mapping(value=None):
    value = value or {}
    allowed = {
        'max_chunks',
        'max_chars',
        'max_relations',
        'max_tokens',
        'related_limit',
        'expansion_depth',
    }
    return {key: val for key, val in value.items() if key in allowed}
