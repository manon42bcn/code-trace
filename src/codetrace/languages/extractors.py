"""Structural unit extractors and optional language-specific chunk metadata."""

from __future__ import annotations

import ast
import re

from ..configuration_chunks import CONFIGURATION_CHUNKING_VERSION, configuration_units
from ..python_parsing import parse_python


def python_units(source: str, *, filename='<unknown>', diagnostics=None):
    tree = parse_python(source, filename=filename, diagnostics=diagnostics)
    nodes = []

    def walk(body, prefix=''):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbol = prefix + node.name
                nodes.append(
                    (
                        min([node.lineno] + [d.lineno for d in node.decorator_list]),
                        node.end_lineno,
                        symbol,
                        'python_ast',
                    )
                )
                if isinstance(node, ast.ClassDef):
                    walk(node.body, symbol + '.')

    walk(tree.body)
    return nodes


def parse_treesitter_units(
    source: str,
    language: str,
    grammar: str,
    node_types: frozenset[str],
    *,
    recover: bool = False,
    diagnostics: list | None = None,
):
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError as exc:
        raise ValueError(
            'Falta tree-sitter-language-pack: ejecuta uv sync --extra parsers'
        ) from exc
    try:
        parser = get_parser(grammar)
        encoded = source.encode('utf-8')
        root = parser.parse(encoded).root_node
    except Exception as exc:
        raise ValueError(f'No se pudo analizar {language} con Tree-sitter: {exc}') from exc
    # Tuple access avoids the Point attribute refcount bug in tree-sitter 0.26.0.
    if root.has_error:
        errors = []

        def collect(node):
            if node.type == 'ERROR' or node.is_missing:
                errors.append(
                    {
                        'line': node.start_point[0] + 1,
                        'column': node.start_point[1] + 1,
                        'node': node.type,
                        'end_line': node.end_point[0] + 1,
                    }
                )
                return
            for child in node.children:
                collect(child)

        collect(root)
        if diagnostics is not None:
            diagnostics.extend(
                {'type': 'syntax_error', 'language': language, **e} for e in errors[:100]
            )
        if not recover:
            loc = errors[0] if errors else {'line': '?', 'column': '?'}
            raise ValueError(
                f'Errores de sintaxis detectados por Tree-sitter en {language} '
                f'(línea {loc["line"]}, columna {loc["column"]})'
            )
    units = []

    def visit(node, parent=''):
        for ch in node.named_children:
            if ch.type in node_types and not ch.has_error:
                ident = ch.child_by_field_name('name') or ch.child_by_field_name('declarator')
                label = (
                    encoded[ident.start_byte : ident.end_byte].decode('utf-8', 'replace')
                    if ident
                    else ch.type
                )
                label = re.sub(r'\s+', ' ', label)[:100]
                symbol = (parent + '.' if parent else '') + label
                units.append((ch.start_point[0] + 1, ch.end_point[0] + 1, symbol, 'tree_sitter'))
                visit(ch, symbol)
            else:
                visit(ch, parent)

    visit(root)
    return units


def make_units(source: str):
    lines = source.splitlines()
    starts = []
    for i, line in enumerate(lines, 1):
        if (
            line.startswith((' ', '\t', '#', '.PHONY'))
            or '=' in line.split(':', 1)[0]
            or ':' not in line
        ):
            continue
        # Targets may contain substitutions such as $(NAME) and pattern rules.
        if re.match(r'^[^\s:#][^:]*:(?!=)', line) and not line.startswith(
            ('ifeq', 'ifneq', 'ifdef', 'ifndef', 'endif')
        ):
            starts.append(i)
    return [
        (
            a,
            starts[j + 1] - 1 if j + 1 < len(starts) else len(lines),
            lines[a - 1].split(':', 1)[0].strip(),
            'makefile_rules',
        )
        for j, a in enumerate(starts)
    ]


def gherkin_units(source: str):
    """Recognize Gherkin sections, preserving tags and Scenario Outline examples.

    Sections are extracted without execution and tolerate localized keywords.
    """
    lines = source.splitlines()
    pattern = re.compile(
        (
            '^\\s*(Feature|Background|Scenario Outline|Scenario Template|'
            'Scenario|Rule|Examples|Example|Característica|Antecedentes|'
            'Esquema del escenario|Escenario|Regla|Ejemplos)\\s*:'
        ),
        re.I,
    )
    sections = []
    pending = None
    for i, line in enumerate(lines, 1):
        if line.strip().startswith('@'):
            if pending is None:
                pending = i
            continue
        match = pattern.match(line)
        if match:
            start = pending or i
            label = line.strip().split(':', 1)[1].strip()
            kind = match.group(1).lower().replace(' ', '_')
            sections.append((start, i, kind, label))
            pending = None
        elif line.strip() and not line.lstrip().startswith('#'):
            pending = None
    # Keep whole scenarios, incl. Examples (do not make Examples independent chunks).
    primary = [v for v in sections if v[2] not in ('examples', 'example', 'ejemplos')]
    units = []
    for j, (start, head, kind, label) in enumerate(primary):
        end = primary[j + 1][0] - 1 if j + 1 < len(primary) else len(lines)
        # Feature / Rule are parents, not a giant chunk consuming nested scenarios.
        if kind in ('feature', 'característica', 'rule', 'regla'):
            end = head
        units.append((start, end, f'{kind}: {label}', 'gherkin_ast'))
    return units


def extract_configuration(source, *, language, syntax_policy, diagnostics, **_options):
    try:
        return configuration_units(source, language)
    except ValueError as exc:
        if syntax_policy != 'recover':
            raise
        if diagnostics is not None:
            diagnostics.append(
                {
                    'type': 'configuration_parse_error',
                    'language': language,
                    'message': str(exc),
                    'recovery': 'raw_document',
                }
            )
        return []


def finalize_configuration(_lines, chunks, chunking_options):
    for row in chunks:
        row['configuration_chunking_version'] = CONFIGURATION_CHUNKING_VERSION
        row['data_path'] = row['symbol']
        if chunking_options['include_parent_context'] and row['symbol'] and '/' in row['symbol']:
            row['parent_symbol'] = row['symbol'].rsplit('/', 1)[0]


def finalize_gherkin(lines, chunks, _chunking_options):
    # Enrich scenario chunks with their feature context (including inherited tags).
    feature = None
    feature_tags = []
    pending_tags = []
    feature_positions = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('@'):
            pending_tags.extend(stripped.split())
        elif re.match(r'^(Feature|Característica)\s*:', stripped, re.I):
            feature = stripped.split(':', 1)[1].strip()
            feature_tags = pending_tags[:]
            feature_positions.append((lineno, feature, feature_tags))
            pending_tags = []
        elif re.match(
            (
                '^(Scenario|Scenario Outline|Scenario Template|Background|'
                'Escenario|Esquema del escenario|Antecedentes)\\s*:'
            ),
            stripped,
            re.I,
        ):
            pending_tags = []
        elif stripped and not stripped.startswith('#'):
            pending_tags = []
    for row in chunks:
        if row['symbol'] and row['symbol'].startswith(
            (
                'scenario:',
                'scenario_outline:',
                'scenario_template:',
                'background:',
                'escenario:',
                'esquema_del_escenario:',
                'antecedentes:',
            )
        ):
            ancestors = [
                (name, tags) for pos, name, tags in feature_positions if pos <= row['start_line']
            ]
            if ancestors:
                name, tags = ancestors[-1]
                row['parent_symbol'] = 'feature: ' + name
                row['feature_tags'] = tags
