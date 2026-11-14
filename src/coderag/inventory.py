"""Complete scoped list inventories from indexed YAML/JSON snapshots, without an LLM."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from bisect import bisect_right
from pathlib import Path

from .answer_display import inline
from .configuration_chunks import parse_configuration
from .repository_paths import repository_index_path
from .repository_routing import select_repository

LIMITATION = (
    'Complete only for the selected list in the indexed snapshot; not runtime registration.'
)


class InventoryError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def walk(node, path):
    yield path, node
    for label, _, child in node.children:
        escaped = label.replace('~', '~0').replace('/', '~1')
        yield from walk(child, f'{path}/{escaped}')


def scalar_field(node, key, position):
    values = {label: value for label, _, value in node.children} if node.kind == 'mapping' else {}
    if '<<' in values or node.kind != 'mapping' or len(values) != len(node.children):
        raise InventoryError(
            'field_unresolved', f'Entry {position}: mapping/merge cannot be resolved.'
        )
    value = values.get(key)
    if value is None:
        return None
    if value.kind != 'scalar' or value.value is None:
        raise InventoryError(
            'field_unresolved', f'Entry {position}: {key!r} is not a string scalar.'
        )
    return value.value


def inventory(
    index,
    *,
    repository=None,
    file=None,
    path=None,
    unique_by=None,
    where=None,
    group_by=None,
    kind='list',
    decorator=None,
):
    if kind == 'python-decorators':
        if path or unique_by or where or group_by:
            raise InventoryError(
                'invalid_options', 'List options cannot be used with Python decorators.'
            )
        from .python_inventory import python_inventory

        return python_inventory(index, repository=repository, file=file, decorator=decorator)
    if kind != 'list' or decorator is not None:
        raise InventoryError('invalid_options', 'Use --kind python-decorators with --decorator.')
    filters = []
    for predicate in where or []:
        key, separator, value = predicate.partition('=')
        if not separator or not key:
            raise InventoryError('invalid_filter', 'Use --where FIELD=VALUE (exact string match).')
        filters.append((key, value))

    snapshots = index.get('configuration_sources')
    if not isinstance(snapshots, dict):
        raise InventoryError(
            'inventory_unavailable', 'Rebuild indexes to include configuration snapshots.'
        )
    scopes = []
    issues = []
    present_non_list = False
    for filename, snapshot in sorted(snapshots.items()):
        if file is not None and filename != file:
            continue
        try:
            source = snapshot['source']
            digest = hashlib.sha256(source.encode()).hexdigest()
            if digest != snapshot['file_sha256']:
                raise ValueError('Indexed snapshot hash mismatch')
            roots = parse_configuration(source, snapshot['language'])
            for number, root in enumerate(roots):
                prefix = '$' if len(roots) == 1 else f'$doc/{number}'
                for data_path, node in walk(root, prefix):
                    if path is not None and data_path != path:
                        continue
                    if node.kind != 'sequence':
                        present_non_list = present_non_list or path == data_path
                        continue
                    scope = {
                        'repository': repository,
                        'file': filename,
                        'data_path': data_path,
                        'entries': len(node.children),
                        'source_sha256': digest,
                    }
                    scopes.append((scope, node, source))
        except (ValueError, KeyError) as exc:
            issues.append({'file': filename, 'message': str(exc)})
    base = {
        'schema_version': '1',
        'repository': repository,
        'total': None,
        'complete': False,
        'items': [],
        'limitations': [LIMITATION],
        'issues': issues,
    }
    if not scopes:
        code = 'scope_not_list' if present_non_list else 'scope_not_found'
        if issues:
            code = 'snapshot_invalid'
        raise InventoryError(
            code, 'No valid list matches this scope; check file/path and index diagnostics.'
        )
    if len(scopes) > 1:
        return {**base, 'status': 'needs_scope', 'scopes': [scope for scope, _, _ in scopes]}
    scope, node, source = scopes[0]
    starts = [0, *(match.end() for match in re.finditer('\n', source))]
    groups = {}
    summaries = {}
    matched_entries = 0
    for position, (_, _, child) in enumerate(node.children):
        field_values = [scalar_field(child, key, position) for key, _ in filters]
        if any(
            actual != expected for actual, (_, expected) in zip(field_values, filters, strict=True)
        ):
            continue
        matched_entries += 1
        group_value = None
        if group_by is not None:
            group_value = scalar_field(child, group_by, position)
            if group_value is None or not group_value.strip():
                raise InventoryError('group_unresolved', f'Entry {position} has no group identity.')
        identity = str(position)
        name = child.value if child.kind == 'scalar' else None
        if unique_by is not None:
            value = scalar_field(child, unique_by, position)
            if value is None or not value.strip():
                raise InventoryError(
                    'identity_unresolved',
                    f'Entry {position} has no scalar {unique_by!r}; no partial count returned.',
                )
            identity = name = value
        end = child.end
        while end > child.start and source[end - 1].isspace():
            end -= 1
        citation = {
            'path': scope['file'],
            'start_line': bisect_right(starts, child.start),
            'end_line': bisect_right(starts, max(child.start, end - 1)),
            'start_offset': child.start,
            'end_offset': end,
            'source_sha256': scope['source_sha256'],
        }
        occurrence = {
            'position': position,
            'data_path': f'{scope["data_path"]}/{position}',
            'citation': citation,
            'content': source[child.start : end],
        }
        if group_by is not None:
            summary = summaries.setdefault(group_value, {'entries': 0, 'identities': set()})
            summary['entries'] += 1
            summary['identities'].add(identity)
        groups.setdefault(identity, {'name': name, 'occurrences': []})['occurrences'].append(
            occurrence
        )
    return {
        **base,
        'status': 'ok',
        'scope': scope,
        'total': len(groups),
        'complete': True,
        'count_mode': 'unique_by' if unique_by else 'entries',
        'unique_by': unique_by,
        'entries': matched_entries,
        'source_entries': len(node.children),
        'filtered_out': len(node.children) - matched_entries,
        'filters': [{'field': key, 'equals': value} for key, value in filters],
        'group_by': group_by,
        'groups': [
            {'value': key, 'entries': value['entries'], 'total': len(value['identities'])}
            for key, value in sorted(summaries.items())
        ],
        'duplicates': matched_entries - len(groups),
        'items': list(groups.values()),
    }


def page_result(result, *, offset=0, limit=20, max_chars=800, max_occurrences=3):
    """Pagination clips presentation only; counting always uses the complete selected list."""
    key = 'scopes' if result['status'] == 'needs_scope' else 'items'
    values = result[key]
    output = {
        **result,
        key: values[offset : offset + limit],
        'pagination': {
            'offset': offset,
            'limit': limit,
            'returned': len(values[offset : offset + limit]),
            'total': len(values),
            'has_more': offset + limit < len(values),
        },
    }
    if result.get('group_by') is not None:
        groups = result['groups']
        output['groups'] = groups[offset : offset + limit]
        output['groups_pagination'] = {
            'offset': offset,
            'limit': limit,
            'total': len(groups),
            'has_more': offset + limit < len(groups),
        }
    if key == 'items':
        output['items'] = [
            {
                **item,
                'occurrences_total': len(item['occurrences']),
                'occurrences_truncated': len(item['occurrences']) > max_occurrences,
                'occurrences': [
                    {
                        **occurrence,
                        'content': occurrence['content'][:max_chars],
                        'truncated': len(occurrence['content']) > max_chars,
                    }
                    for occurrence in item['occurrences'][:max_occurrences]
                ],
            }
            for item in output['items']
        ]
    return output


def markdown(result):
    if result['status'] == 'needs_scope':
        lines = [
            '## Inventario: selecciona el alcance',
            '',
            'Hay varias listas. Indica el archivo y la ruta de la lista que quieres contar.',
            '',
        ]
        lines.extend(
            f'- {inline(scope["file"])} — {inline(scope["data_path"])} '
            f'({scope["entries"]} entradas)'
            for scope in result['scopes']
        )
    else:
        scope = result['scope']
        lines = [
            '## Inventario',
            '',
            f'**Repositorio:** {inline(result["repository"])}',
            f'**Archivo:** {inline(scope["file"])}',
            f'**Alcance:** {inline(scope["data_path"])}',
            f'**Total:** {result["total"]}',
            '**Completo:** sí, para el patrón/alcance seleccionado en la versión indexada.',
            f'**Entradas:** {result["entries"]} · **Duplicados agrupados:** {result["duplicates"]}',
            '',
        ]
        if result.get('unsupported_decorator_expressions'):
            lines += [
                f'**Expresiones de decorador no resueltas:** '
                f'{result["unsupported_decorator_expressions"]}',
                '',
            ]
        if result.get('filters'):
            lines += [
                f'**Filtros:** {inline(str(result["filters"]))}',
                f'**Entradas originales:** {result["source_entries"]} · '
                f'**Excluidas por filtros:** {result["filtered_out"]}',
                '',
            ]
        if result.get('groups'):
            lines += [f'**Agrupación:** {inline(result["group_by"])}', '']
            lines += [
                f'- {inline(group["value"])}: {group["total"]} ({group["entries"]} entradas)'
                for group in result['groups']
            ]
        if result.get('groups_pagination'):
            group_page = result['groups_pagination']
            lines += [
                f'Grupos mostrados: {len(result["groups"])} de {group_page["total"]}, '
                f'offset {group_page["offset"]}.',
                '',
            ]
        for number, item in enumerate(result['items'], result['pagination']['offset'] + 1):
            lines += [f'### {number}. {inline(item["name"] or "Entrada")}', '']
            for occurrence in item['occurrences']:
                cite = occurrence['citation']
                lines += [
                    f'{inline(cite["path"])}:{cite["start_line"]}-{cite["end_line"]} '
                    f'— {inline(occurrence["data_path"])}',
                    '',
                ]
                fence = '`' * max(
                    3,
                    max(
                        (len(m.group()) for m in re.finditer(r'`+', occurrence['content'])),
                        default=0,
                    )
                    + 1,
                )
                lines += [fence, occurrence['content'], fence, '']
                if occurrence.get('truncated'):
                    lines += [
                        'Fragmento truncado para presentación; el conteo no se ha truncado.',
                        '',
                    ]
        if any(item.get('occurrences_truncated') for item in result['items']):
            lines += [
                'Se muestran algunas ocurrencias de duplicados; el informe conserva todas.',
                '',
            ]
    pagination = result['pagination']
    lines += [
        f'Página: {pagination["returned"]} de {pagination["total"]}, '
        f'offset {pagination["offset"]}.',
        '',
        '## Limitaciones',
        '',
        *[f'- {note}' for note in result['limitations']],
    ]
    if result['issues']:
        lines += [
            '',
            f'Otros documentos con errores: {len(result["issues"])}. Revisa el informe JSON.',
        ]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('query', nargs='?', default='')
    parser.add_argument('--config', type=Path, default=Path('config.json'))
    parser.add_argument('--repo')
    parser.add_argument('--default-repo')
    parser.add_argument('--file')
    parser.add_argument('--path')
    parser.add_argument('--unique-by')
    parser.add_argument(
        '--where', action='append', help='Repeatable FIELD=VALUE string filters (AND)'
    )
    parser.add_argument('--group-by')
    parser.add_argument('--kind', choices=('list', 'python-decorators'), default='list')
    parser.add_argument(
        '--decorator', help='Exact syntactic decorator name, e.g. step or behave.step'
    )
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--max-evidence-chars', type=int, default=800)
    parser.add_argument('--max-occurrences', type=int, default=3)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--output-format', choices=('json', 'markdown'), default='json')
    args = parser.parse_args(argv)
    try:
        if (
            args.offset < 0
            or not 1 <= args.limit <= 200
            or args.max_evidence_chars < 1
            or not 1 <= args.max_occurrences <= 20
        ):
            raise ValueError('Use offset >= 0, limit between 1 and 200, and positive evidence size')
        config = json.loads(args.config.read_text(encoding='utf-8'))
        repo = args.repo or args.default_repo or config.get('default_repository')
        routing = None
        if args.default_repo:
            routing = select_repository(
                args.query, config.get('repositories', {}), repo, repo=args.repo
            )
            repo = routing['repository']
        index = json.loads(
            repository_index_path(config, args.config, repo).read_text(encoding='utf-8')
        )
        full = inventory(
            index,
            repository=repo,
            file=args.file,
            path=args.path,
            unique_by=args.unique_by,
            where=args.where,
            group_by=args.group_by,
            kind=args.kind,
            decorator=args.decorator,
        )
        if routing:
            full['routing'] = routing
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(full, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
            )
        output = page_result(
            full,
            offset=args.offset,
            limit=args.limit,
            max_chars=args.max_evidence_chars,
            max_occurrences=args.max_occurrences,
        )
        rendered = (
            markdown(output)
            if args.output_format == 'markdown'
            else json.dumps(output, ensure_ascii=False, indent=2)
        )
        print(rendered)  # noqa: T201 - CLI output
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(  # noqa: T201 - CLI output
            json.dumps(
                {
                    'schema_version': '1',
                    'status': 'error',
                    'complete': False,
                    'error': {
                        'code': getattr(exc, 'code', 'inventory_failed'),
                        'message': str(exc),
                        **({'candidates': exc.candidates} if hasattr(exc, 'candidates') else {}),
                    },
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from exc
