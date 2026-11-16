"""Inventory explicitly named Python function decorators in one indexed source snapshot."""

import ast
import hashlib

from .python_parsing import parse_python


def decorator_name(node):
    if isinstance(node, ast.Call):
        node = node.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return '.'.join([node.id, *reversed(parts)])
    return None


def python_inventory(index, *, repository=None, file=None, decorator=None):
    from .inventory import InventoryError

    if not file or not decorator or any(not part.isidentifier() for part in decorator.split('.')):
        raise InventoryError(
            'scope_required', 'Specify --file and an exact dotted --decorator name.'
        )
    snapshots = index.get('python_sources')
    if not isinstance(snapshots, dict):
        raise InventoryError('inventory_unavailable', 'Reindex once to add full Python snapshots.')
    if file not in snapshots:
        raise InventoryError('scope_not_found', 'Python file not present in indexed snapshots.')
    try:
        source = snapshots[file]['source']
        if not isinstance(source, str):
            raise ValueError('Snapshot source must be text')
        digest = hashlib.sha256(source.encode()).hexdigest()
        if digest != snapshots[file]['file_sha256']:
            raise ValueError('Snapshot hash mismatch')
        tree = parse_python(source, filename=file, quiet=True)
    except (ValueError, SyntaxError, KeyError, TypeError) as exc:
        raise InventoryError(
            'snapshot_invalid', 'Cannot parse/verify indexed Python source.'
        ) from exc
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    items = []
    unsupported = 0

    def visit(node, prefix=''):
        nonlocal unsupported
        qualified = prefix
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            qualified = f'{prefix}.{node.name}' if prefix else node.name
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [d for d in node.decorator_list if decorator_name(d) == decorator]
            unsupported += sum(decorator_name(d) is None for d in node.decorator_list)
            if decorators:
                occurrences = []
                for dec in decorators:
                    start = starts[dec.lineno - 1]
                    end = starts[node.end_lineno]
                    occurrences.append(
                        {
                            'position': len(items),
                            'data_path': qualified,
                            'citation': {
                                'path': file,
                                'start_line': dec.lineno,
                                'end_line': node.end_lineno,
                                'start_offset': start,
                                'end_offset': end,
                                'source_sha256': digest,
                            },
                            'content': source[start:end],
                        }
                    )
                items.append({'name': qualified, 'occurrences': occurrences})
        for child in ast.iter_child_nodes(node):
            visit(child, qualified)

    visit(tree)
    entries = sum(len(item['occurrences']) for item in items)
    return {
        'schema_version': '1',
        'status': 'ok',
        'kind': 'python-decorators',
        'repository': repository,
        'complete': True,
        'total': len(items),
        'entries': entries,
        'duplicates': entries - len(items),
        'count_mode': 'decorated_functions',
        'unique_by': None,
        'items': items,
        'issues': [],
        'scope': {
            'repository': repository,
            'file': file,
            'data_path': f'python:decorator:{decorator}',
            'source_sha256': digest,
            'decorator': decorator,
        },
        'unsupported_decorator_expressions': unsupported,
        'limitations': [
            'Complete only for functions with this exact syntactic decorator in the indexed file.',
            'Aliases, imports, conditional reachability and runtime registration are not resolved.',
            'Class decorators are excluded; nested and async functions are included.',
            'Non-name decorator expressions are counted as unsupported, never executed.',
        ],
    }
