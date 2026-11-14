"""Explicit, offline cross-repository Behave linking.

A dependency grants *search visibility*, not proof that Behave imports it at runtime.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .artifact_state import file_stamp, link_signature
from .behave_links import _definitions
from .repository_paths import index_output, repository_index_path


def _scope(path: str) -> str:
    """Identify a local Behave suite. Separate e.g. web_behave and web_playwright_behave."""
    parts = PurePosixPath(path).parts
    if 'features' in parts:
        i = parts.index('features')
        return '/'.join(parts[: i + 1])
    return parts[0] if len(parts) > 1 else '.'


def _definition_in_scope(path: str, scope: str) -> bool:
    # Standard Behave: features/steps/**/*.py. Also support common example layout suite/steps.
    pp = PurePosixPath(path)
    candidates = (scope + '/steps/', scope.rsplit('/features', 1)[0] + '/steps/')
    return any(path.startswith(c) for c in candidates) or (scope == '.' and 'steps' in pp.parts)


def _deps(config: dict, repo: str) -> list[str]:
    relationship = config.get('relationships', {}).get(repo, {})
    if isinstance(relationship, list):
        return relationship
    return relationship.get('dependencies', [])


def _transitive(config: dict, root: str) -> list[str]:
    ordered = []
    seen = {root}

    def walk(node):
        for dep in _deps(config, node):
            if dep not in seen:
                seen.add(dep)
                ordered.append(dep)
                walk(dep)

    walk(root)
    return ordered


def _matches(definitions, text, effective_keyword):
    return [
        d
        for d in definitions
        if d['keyword'] in ('step', effective_keyword)
        and d['_regex'] is not None
        and d['_regex'].fullmatch(text)
    ]


def _deduplicate(definitions):
    """Multiple decorators of one function represent one implementation."""
    unique = {}
    for d in definitions:
        unique.setdefault((d['path'], d['chunk_id'], d['function']), d)
    return list(unique.values())


def _under(path, root):
    root = root.strip('/')
    return path.startswith(root + '/') if root else True


def _scope_roots(config, repo, scope):
    """Configured features-to-step-roots mapping; fallback to standard layout."""
    setup = config.get('relationships', {}).get(repo, {})
    if not isinstance(setup, dict):
        return None
    for item in setup.get('behave_scopes', []):
        feature_root = item.get('features', '').strip('/')
        if feature_root and (scope == feature_root or scope.startswith(feature_root + '/')):
            return item.get('steps', [])
    return None


def _exported(config, dep, definitions):
    relation = config.get('relationships', {}).get(dep, {})
    roots = relation.get('exported_steps') if isinstance(relation, dict) else None
    if roots is None:
        return definitions  # Backwards compatible, but runtime still unverified.
    return [d for d in definitions if any(_under(d['path'], r) for r in roots)]


def _public(d, repository):
    return {
        'repository': repository,
        'chunk_id': d['chunk_id'],
        'path': d['path'],
        'function': d['function'],
        'pattern': d['pattern'],
        'keyword': d['keyword'],
    }


def _outline_rows(content: str) -> list[dict[str, str]]:
    """Extract Gherkin Examples rows from an indexed scenario outline.

    Multiple Examples blocks are allowed. Steps and doc-string tables are not
    interpreted as Examples. Malformed tables are conservatively ignored.
    """
    rows = []
    examples = False
    headings = None
    for raw in content.splitlines():
        line = raw.strip()
        if re.match(r'^(?:Examples|Ejemplos)\s*:', line, re.I):
            examples, headings = True, None
            continue
        if not examples:
            continue
        if line.startswith('|') and line.endswith('|'):
            fields = [v.strip().replace(r'\|', '|') for v in re.split(r'(?<!\\)\|', line[1:-1])]
            if headings is None:
                headings = fields
            elif len(fields) == len(headings):
                rows.append(dict(zip(headings, fields, strict=True)))
        elif line and not line.startswith(('@', '#')):
            examples, headings = False, None
    return rows


def _variants(text: str, rows: list[dict[str, str]]) -> list[str]:
    if not rows or not re.search(r'<[^<>]+>', text):
        return [text]
    out = []
    for row in rows:
        value = re.sub(r'<([^<>]+)>', lambda m, row=row: row.get(m.group(1), m.group(0)), text)
        if value not in out:
            out.append(value)
    return out or [text]


def _expanded_rows(text: str, rows: list[dict[str, str]]) -> list[dict]:
    """Preserve Examples identity; never combine definitions from different rows."""
    if not rows or not re.search(r'<[^<>]+>', text):
        return [{'text': text, 'example_row': None}]
    return [
        {
            'text': re.sub(r'<([^<>]+)>', lambda m, row=row: row.get(m.group(1), m.group(0)), text),
            'example_row': i + 1,
            'example_values': row,
        }
        for i, row in enumerate(rows)
    ]


def _import_evidence(index: dict, path: str) -> list[dict]:
    """Find static import mentions; imports do not establish Behave registration."""
    module = path.removesuffix('.py').replace('/', '.')
    if module.endswith('.__init__'):
        module = module[:-9]
    matches = []
    for c in index.get('chunks', []):
        if c.get('language') != 'python' or c.get('path') == path:
            continue
        content = c.get('content', '')
        # Structural chunks may contain incomplete code; scan import lines conservatively.
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith(('import ', 'from ')):
                continue
            parent, _, leaf = module.rpartition('.')
            exact_import = bool(
                re.search(r'(?<![\w.])' + re.escape(module) + r'(?![\w.])', stripped)
            )
            from_parent = bool(
                parent
                and leaf
                and stripped.startswith('from ' + parent + ' import ')
                and re.search(r'(?<!\w)' + re.escape(leaf) + r'(?!\w)', stripped)
            )
            if exact_import or from_parent:
                match = {
                    'path': c['path'],
                    'line_approx': c.get('start_line', 1),
                    'kind': 'static_import_reference',
                }
                if match not in matches:
                    matches.append(match)
                break
        if len(matches) >= 5:
            break
    return matches


def _pending_reason(local_defs, all_defs, external_defs, text, keyword) -> str:
    if _matches(all_defs, text, keyword) and not _matches(local_defs, text, keyword):
        return 'matching_definition_outside_local_scope'
    if _matches(all_defs, text, 'step') and not _matches(all_defs, text, keyword):
        return 'step_keyword_mismatch'
    if any(d['_regex'] is None for d in [*all_defs, *external_defs]):
        return 'no_match_or_unsupported_pattern'
    return 'no_matching_definition_in_configured_scopes'


def build_repository_links(config: dict, config_path: Path, repo: str) -> dict:
    repos = config.get('repositories', {})
    if repo not in repos:
        raise ValueError(f'Repositorio no configurado: {repo}')
    names = [repo, *_transitive(config, repo)]
    indexes = {}
    index_stamps = {}
    missing = []
    for name in names:
        if name not in repos:
            missing.append({'repository': name, 'reason': 'not_configured'})
            continue
        path = repository_index_path(config, config_path, name)
        if not path.is_file():
            missing.append(
                {'repository': name, 'reason': 'index_missing', 'expected_output': str(path)}
            )
            continue
        before = file_stamp(path)
        indexes[name] = json.loads(path.read_text(encoding='utf-8'))
        if file_stamp(path) != before:
            raise ValueError(f'Index changed during linking: {name}; retry link')
        index_stamps[name] = before
    if repo not in indexes:
        raise ValueError(f'Falta el índice de origen: {repo}; ejecuta primero coderag index')
    defs = {name: _definitions(idx['chunks']) for name, idx in indexes.items()}
    exported_defs = {name: _exported(config, name, ds) for name, ds in defs.items()}
    source = indexes[repo].get('behave_relations', {}).get('step_occurrences', [])
    chunk_contents = {c['id']: c.get('content', '') for c in indexes[repo]['chunks']}
    outline_cache = {}
    # Keep one record per Gherkin occurrence, and separate per-row relations for outlines.
    scoped_definitions = {}
    match_cache = {}
    results = []
    rows_total = 0
    import_cache = {}
    all_external = [d for name in names[1:] for d in exported_defs.get(name, [])]
    for occ in source:
        scope = _scope(occ['feature_path'])
        if occ['chunk_id'] not in outline_cache:
            outline_cache[occ['chunk_id']] = _outline_rows(chunk_contents.get(occ['chunk_id'], ''))
        variants = _expanded_rows(occ['text'], outline_cache[occ['chunk_id']])
        if scope not in scoped_definitions:
            roots = _scope_roots(config, repo, scope)
            scoped_definitions[scope] = (
                [d for d in defs[repo] if any(_under(d['path'], r) for r in roots)]
                if roots is not None
                else [d for d in defs[repo] if _definition_in_scope(d['path'], scope)]
            )
        for variant in variants:
            step_text = variant['text']
            key = (scope, occ['effective_keyword'], step_text)
            if key not in match_cache:
                local = scoped_definitions[scope]
                selected = _deduplicate(_matches(local, step_text, occ['effective_keyword']))
                candidates = [_public(d, repo) for d in selected]
                if selected:
                    status = 'resolved_local' if len(selected) == 1 else 'ambiguous'
                    tier = 'local_scope'
                else:
                    external = []
                    for dep in names[1:]:
                        external.extend(
                            _public(d, dep)
                            for d in _deduplicate(
                                _matches(
                                    exported_defs.get(dep, []), step_text, occ['effective_keyword']
                                )
                            )
                        )
                    candidates = external
                    status = (
                        'resolved_external'
                        if len(external) == 1
                        else 'ambiguous'
                        if external
                        else 'unresolved'
                    )
                    tier = 'declared_dependencies' if external else 'none'
                reason = (
                    'local_scope_match'
                    if selected
                    else 'external_candidate'
                    if candidates
                    else _pending_reason(
                        local, defs[repo], all_external, step_text, occ['effective_keyword']
                    )
                )
                match_cache[key] = (status, tier, candidates, reason)
            status, tier, candidates, reason = match_cache[key]
            evidence = []
            for d in candidates:
                evidence_key = (d['repository'], d['path'])
                if evidence_key not in import_cache:
                    import_cache[evidence_key] = _import_evidence(
                        indexes[d['repository']], d['path']
                    )
                if import_cache[evidence_key]:
                    evidence.append(
                        {
                            'repository': d['repository'],
                            'definition_path': d['path'],
                            'references': import_cache[evidence_key],
                        }
                    )
            record = {
                'source_repository': repo,
                'feature_path': occ['feature_path'],
                'scenario': occ['scenario'],
                'line_approx': occ['line_approx'],
                'chunk_id': occ['chunk_id'],
                'keyword': occ['keyword'],
                'effective_keyword': occ['effective_keyword'],
                'text': occ['text'],
                'resolved_text': step_text,
                'scope': scope,
                'status': status,
                'resolution_tier': tier,
                'runtime_verified': False,
                'reason': reason,
                'definitions': candidates,
                'outline_variants': len(variants) if len(variants) > 1 else 0,
                'import_evidence': evidence,
            }
            if variant['example_row'] is not None:
                record['example_row'] = variant['example_row']
                record['example_values'] = variant['example_values']
                rows_total += 1
            results.append(record)
    from .toolium_analysis import analyze_toolium

    toolium = analyze_toolium(config, config_path, repo, indexes[repo], results, indexes=indexes)
    counts = Counter(x['status'] for x in results)
    from .capability_contract import attach_capability_contract

    report = {
        'schema_version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source_repository': repo,
        'preparation_signature': link_signature(config, repo),
        'indexed_repositories': names,
        'available_repositories': list(indexes),
        'missing_dependencies': missing,
        'index_sources': {
            name: {
                'output': index_output(config, name),
                'created_at': idx.get('created_at'),
                'file_stamp': index_stamps[name],
                'source_root': idx.get('source_root'),
            }
            for name, idx in indexes.items()
        },
        'summary': {
            'step_occurrences': len(source),
            'evaluated_cases': len(results),
            'outline_cases': rows_total,
            'resolved_local': counts['resolved_local'],
            'resolved_external': counts['resolved_external'],
            'ambiguous': counts['ambiguous'],
            'unresolved': counts['unresolved'],
            'missing_dependencies': len(missing),
        },
        'relations': results,
        'toolium': toolium,
        'disclaimer': (
            'Coincidencias estáticas. Las referencias import no prueban '
            'registro de pasos Behave; el runtime no se verifica.'
        ),
    }
    return attach_capability_contract(report, indexes)


def save_links(output: Path, payload: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            'w',
            encoding='utf-8',
            dir=output.parent,
            prefix=output.name + '.',
            suffix='.tmp',
            delete=False,
        ) as f:
            name = f.name
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(name, output)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
