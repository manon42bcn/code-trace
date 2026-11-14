"""Explainable static identifier ranking; no repository-specific names or model calls."""

import re
from functools import lru_cache

from .configuration_chunks import parse_configuration

RANKING_PROFILE = 'identifier-v2'


@lru_cache(maxsize=128)
def patterns(term):
    escaped = re.escape(term)
    token = re.compile(rf'(?<!\w){escaped}(?!\w)')
    leaf = re.escape(term.rsplit('.', 1)[-1])
    definition = re.compile(rf'^\s*(?:(?:async\s+)?def|class)\s+{leaf}\b', re.MULTILINE)
    return token, definition


@lru_cache(maxsize=128)
def literal_identities(content, language):
    """Inspect direct mapping fields; text examples inside scalar descriptions stay references."""
    if language == 'json' and not content.lstrip().startswith(('{', '[')):
        content = '{' + content + '}'
    try:
        roots = parse_configuration(content, language)
    except ValueError:
        return ()
    mappings = [
        node
        for root in roots
        for node in ([root] if root.kind == 'mapping' else [child for _, _, child in root.children])
        if node.kind == 'mapping'
    ]
    return tuple(
        value.value
        for node in mappings
        for name, _, value in node.children
        if (name in {'name', 'id', 'key'} or name.endswith('_name'))
        and value.kind == 'scalar'
        and value.value is not None
    )


def describe_match(item, term):
    """Signals describe written syntax/metadata, not effective runtime definitions."""

    def result(priority, match, role):
        return {'profile': RANKING_PROFILE, 'priority': priority, 'match': match, 'role': role}

    if not term or not all(part.isidentifier() for part in term.split('.')):
        return result(5, 'legacy', 'unknown')
    token, definition = patterns(term)
    symbol = item.get('symbol') or ''
    content = item.get('content') or ''
    language = item.get('language')
    exact_symbol = symbol == term or ('.' not in term and symbol.rsplit('.', 1)[-1] == term)
    if exact_symbol:
        if (
            item.get('kind') == 'python_symbol'
            or item.get('strategy') == 'tree_sitter'
            or (language == 'python' and definition.search(content))
        ):
            return result(0, 'exact_symbol', 'definition')
        return result(2, 'exact_symbol', 'symbol_context')
    if language in {'yaml', 'json'}:
        data_path = item.get('data_path') or (symbol if symbol.startswith('$') else '')
        parts = [part.replace('~1', '/').replace('~0', '~') for part in data_path.split('/')]
        if parts and parts[-1] == term:
            return result(1, 'exact_key', 'declaration')
        if data_path and term in literal_identities(content, language):
            return result(1, 'exact_identity_value', 'declaration')
        if term in parts:
            return result(2, 'exact_ancestor_key', 'declaration_context')
    if any(token.search(str(item.get(field) or '')) for field in ('symbol', 'content', 'key')):
        role = 'access_reference' if item.get('kind') == 'data_key' else 'reference'
        return result(3, 'identifier_token', role)
    if any(term in str(item.get(field) or '') for field in ('symbol', 'content', 'key', 'path')):
        return result(4, 'substring', 'partial_reference')
    return result(5, 'no_literal_match', 'unknown')


def rank_key(item, *, identity='chunk_id'):
    """Use readable provenance before opaque IDs when semantic relevance is tied."""
    return (
        (item.get('ranking') or {}).get('priority', 5),
        -(item.get('ranking') or {}).get('term_coverage', 0.0),
        -item.get('score', 0.0),
        item.get('path') or '',
        item.get('start_line') or 0,
        item.get('symbol') or '',
        item.get(identity) or '',
    )
