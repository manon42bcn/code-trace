"""Provider-neutral routing for retrieval query intents."""

from __future__ import annotations


def classify_query(term: str, *, kind: str = 'any') -> str:
    """Classify explicit search intent without repository-specific rules."""
    if kind == 'symbol':
        return 'exact_symbol'
    if kind == 'path':
        return 'exact_path'
    if any(char.isspace() for char in term.strip()):
        return 'natural_language'
    if kind == 'content':
        return 'storage_key' if '.' in term or '_' in term else 'natural_language'
    if '/' in term or term.endswith(('.py', '.js', '.ts', '.feature')):
        return 'exact_path'
    if term.isidentifier() and ('_' in term or term[:1].islower()):
        return 'exact_symbol'
    return 'natural_language'


def retrieval_sources(intent: str) -> tuple[str, ...]:
    """Return source priority for a classified query."""
    return {
        'exact_symbol': ('lexical', 'structural'),
        'exact_path': ('lexical', 'structural'),
        'storage_key': ('lexical', 'structural', 'semantic'),
        'natural_language': ('semantic', 'structural', 'lexical'),
        'structural_relation': ('structural', 'lexical', 'semantic'),
    }.get(intent, ('lexical', 'structural', 'semantic'))
