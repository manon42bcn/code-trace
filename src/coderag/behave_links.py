"""Conservative static Gherkin ↔ Python Behave relationship extraction.

No source code is executed. Matches are candidates, not runtime guarantees.
"""

from __future__ import annotations

import ast
import re
import string
from collections import Counter

from .python_parsing import parse_python

STEP = re.compile(r'^\s*(Given|When|Then|And|But|\*)\s+(.+?)\s*$', re.I)
PARAM = re.compile(r'\{[^{}]+\}')


def _pattern_regex(pattern: str):
    """Conservative matcher for Behave parse-style fields and explicit regexes.

    Unknown format specifications do not silently become generic wildcards.
    No regex from a repository is executed as Python code.
    """
    if len(pattern) > 2048:
        return None
    if pattern.startswith('^') or pattern.endswith('$'):
        # Avoid obvious nested repetition hazards in untrusted regexes.
        if re.search(r'\([^)]*[+*][^)]*\)[+*{]', pattern):
            return None
        try:
            return re.compile(pattern)
        except re.error:
            return None
    try:
        parts = list(string.Formatter().parse(pattern))
    except ValueError:
        return None
    expr = '^'
    for index, (literal, field, spec, conversion) in enumerate(parts):
        expr += re.escape(literal)
        if field is None:
            continue
        if conversion is not None:
            return None
        kind = (spec or '').split(':', 1)[0]
        if kind in ('', 's', 'w', 'W'):
            # A quoted field must not consume its closing quote or a subsequent
            # quoted argument. Unquoted fields preserve the existing behavior.
            following = parts[index + 1][0] if index + 1 < len(parts) else ''
            if literal.endswith('"') and following.startswith('"'):
                expr += r'([^\"\n]+)'
            elif literal.endswith("'") and following.startswith("'"):
                expr += r"([^'\n]+)"
            else:
                expr += r'(.+?)'
        elif kind in ('d', 'n'):
            expr += r'([+-]?\d+)'
        elif kind in ('f', 'g', 'e', '%'):
            expr += r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'
        else:
            return None
    try:
        return re.compile(expr + '$')
    except re.error:
        return None


def _definitions(chunks):
    definitions = []
    for c in chunks:
        if c.get('language') != 'python' or c.get('strategy') != 'python_ast':
            continue
        try:
            tree = parse_python(c['content'].lstrip(), quiet=True)
        except (SyntaxError, IndentationError):
            continue
        for func in tree.body:
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in func.decorator_list:
                if not isinstance(d, ast.Call) or not d.args:
                    continue
                fn = d.func
                kind = (
                    fn.id
                    if isinstance(fn, ast.Name)
                    else fn.attr
                    if isinstance(fn, ast.Attribute)
                    else None
                )
                if kind not in ('given', 'when', 'then', 'step'):
                    continue
                if not isinstance(d.args[0], ast.Constant) or not isinstance(d.args[0].value, str):
                    continue
                pattern = d.args[0].value
                regex = _pattern_regex(pattern)
                definitions.append(
                    {
                        'chunk_id': c['id'],
                        'path': c['path'],
                        'line': c['start_line'],
                        'function': c.get('symbol') or func.name,
                        'keyword': kind,
                        'pattern': pattern,
                        'match_supported': regex is not None,
                        '_regex': regex,
                    }
                )
    return definitions


def build_behave_relations(chunks):
    defs = _definitions(chunks)
    occurrences = []
    feature_count = 0
    scenario_count = 0
    for c in chunks:
        if c.get('language') != 'gherkin':
            continue
        symbol = c.get('symbol') or ''
        if symbol.startswith(('feature:', 'característica:')):
            feature_count += 1
        if symbol.startswith(
            (
                'scenario:',
                'scenario_outline:',
                'scenario_template:',
                'escenario:',
                'esquema_del_escenario:',
            )
        ):
            scenario_count += 1
        # Ignore neighboring pieces; only scenario/background blocks contain steps.
        if not symbol.startswith(
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
            continue
        previous = None
        for offset, line in enumerate(c['content'].splitlines()):
            m = STEP.match(line)
            if not m:
                continue
            keyword, text = m.groups()
            normalized = previous if keyword.lower() in ('and', 'but') else keyword.lower()
            if keyword.lower() not in ('and', 'but', '*'):
                previous = normalized
            # local definitions are favored, but shared steps can live outside the feature subtree.
            candidates = []
            for d in defs:
                if normalized and d['keyword'] not in ('step', normalized):
                    continue
                if d['_regex'] is not None and d['_regex'].fullmatch(text):
                    candidates.append(d)
            # Never silently pick one implementation: report ambiguity explicitly.
            matches = [
                {
                    'chunk_id': d['chunk_id'],
                    'path': d['path'],
                    'function': d['function'],
                    'pattern': d['pattern'],
                }
                for d in candidates
            ]
            status = 'resolved' if len(matches) == 1 else 'ambiguous' if matches else 'unmatched'
            occurrences.append(
                {
                    'feature_path': c['path'],
                    'scenario': symbol,
                    'chunk_id': c['id'],
                    'line_approx': c['start_line'] + offset,
                    'keyword': keyword,
                    'effective_keyword': normalized,
                    'text': text,
                    'status': status,
                    'definitions': matches,
                }
            )
    public_defs = [{k: v for k, v in d.items() if k != '_regex'} for d in defs]
    counts = Counter(o['status'] for o in occurrences)
    return {
        'feature_chunks': feature_count,
        'scenario_chunks': scenario_count,
        'step_definitions': public_defs,
        'step_occurrences': occurrences,
        'summary': {
            'step_definitions': len(defs),
            'step_occurrences': len(occurrences),
            'resolved': counts['resolved'],
            'ambiguous': counts['ambiguous'],
            'unmatched': counts['unmatched'],
            'matching': 'static_candidates_parse_style_and_basic_regex',
        },
    }
