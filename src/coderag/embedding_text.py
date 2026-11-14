"""Deterministic text representation used by embedding providers."""

from __future__ import annotations

EMBEDDING_TEXT_VERSION = 'v2'


def chunk_embedding_text(
    chunk: dict,
    *,
    repository: str | None = None,
    related_keys: list[str] | None = None,
    access_types: list[str] | None = None,
    relations: list[str] | None = None,
) -> str:
    """Render stable metadata, optional evidence, and source content."""
    fields = [
        ('Repository', repository or chunk.get('repository', '')),
        ('Path', chunk.get('path', '')),
        ('Language', chunk.get('language', '')),
        ('Symbol', chunk.get('symbol', '')),
        ('Parent', chunk.get('parent_symbol', '')),
    ]
    extras = [
        ('Related keys', ', '.join(sorted(set(related_keys or [])))),
        ('Access types', ', '.join(sorted(set(access_types or [])))),
        ('Relations', ', '.join(sorted(set(relations or [])))),
    ]
    header = '\n'.join(f'{name}: {value}' for name, value in (*fields, *extras) if value)
    return (
        f'{header}\nCode:\n{chunk.get("content", "")}'
        if header
        else f'Code:\n{chunk.get("content", "")}'
    )
