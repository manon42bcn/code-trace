"""Bounded, offline evidence paths from preceding Behave steps to Python writers.

A route means syntactic reachability through statically bound functions, not execution.
"""

from __future__ import annotations

import ast
import textwrap
from collections import defaultdict

from .python_parsing import parse_python


def _module(path):
    result = path.removesuffix('.py').replace('/', '.')
    return result[:-9] if result.endswith('.__init__') else result


def _resolve_import_module(path, node):
    """Resolve Python relative imports against the importing package.

    Escaping the package root is not treated as a known import.
    """
    if not node.level:
        return node.module
    parent = _module(path).split('.')[:-1]
    drop = node.level - 1
    if drop > len(parent):
        return None
    prefix = parent[: len(parent) - drop] if drop else parent
    suffix = node.module.split('.') if node.module else []
    return '.'.join(prefix + suffix) or None


def _tree(source):
    try:
        return parse_python(textwrap.dedent(source), quiet=True)
    except (SyntaxError, ValueError):
        return None


def call_graph(indexes):
    """Resolve plain function calls, explicit imports, and module-qualified calls.

    Reject ambiguous symbols, star imports, instance methods and dynamic dispatch.
    """
    symbols = defaultdict(list)
    imports = defaultdict(dict)
    functions = []
    globally = defaultdict(list)
    for repo, index in indexes.items():
        for chunk in index.get('chunks', []):
            if chunk.get('language') != 'python':
                continue
            path = chunk['path']
            if chunk.get('strategy') == 'python_ast' and chunk.get('symbol'):
                symbol = chunk['symbol']
                if '.' not in symbol:  # top-level functions only; avoid method dispatch assumptions
                    record = (repo, chunk['id'])
                    symbols[(repo, _module(path), symbol)].append(record)
                    functions.append((repo, path, chunk, record))
                    globally[(_module(path), symbol)].append(record)
            # imports often live in surrounding_code chunks
            tree = _tree(chunk.get('content', ''))
            if tree is None:
                continue
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports[(repo, path)][alias.asname or alias.name.split('.')[0]] = (
                            'module',
                            alias.name,
                        )
                elif isinstance(node, ast.ImportFrom):
                    module = _resolve_import_module(path, node)
                    if module:
                        for alias in node.names:
                            if alias.name != '*':
                                imports[(repo, path)][alias.asname or alias.name] = (
                                    'symbol',
                                    module,
                                    alias.name,
                                )
    graph = defaultdict(set)
    diagnostics = defaultdict(set)
    for repo, path, chunk, origin in functions:
        tree = _tree(chunk.get('content', ''))
        if tree is None:
            continue
        local = _module(path)
        bindings = imports[(repo, path)]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
                bind = bindings.get(name)
                if bind and bind[0] == 'symbol':
                    target = (bind[1], bind[2])
                elif not bind:
                    target = (local, name)
            elif isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                base = node.func.value
                if isinstance(base, ast.Name):
                    bind = bindings.get(base.id)
                    if bind and bind[0] == 'module':
                        target = (bind[1], attr)
                # One-hop attribute on a package-qualified import is only
                # resolved when its complete module is explicit in imports.
            if not target:
                continue
            found = symbols.get((repo, *target), [])
            if not found:
                # Cross-repository resolution is allowed only for an explicit
                # import and a unique fully-qualified module/function.
                binding_present = (
                    isinstance(node.func, ast.Name)
                    and bindings.get(node.func.id, ('',))[0] == 'symbol'
                ) or (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and bindings.get(node.func.value.id, ('',))[0] == 'module'
                )
                if binding_present:
                    found = globally.get(target, [])
            if len(found) == 1 and found[0] != origin:
                graph[origin].add(found[0])
            elif len(found) > 1:
                diagnostics[origin].add('ambiguous_import_target')
            elif target[0] != local:
                diagnostics[origin].add('unresolved_import_target')
    return graph, diagnostics


def reachable(graph, start, max_depth=4, max_nodes=80):
    """Yield bounded witness paths; cycle safe and deterministic."""
    queue = [(start,)]
    seen = {start}
    while queue:
        chain = queue.pop(0)
        yield chain
        if len(chain) - 1 >= max_depth:
            continue
        for neighbor in sorted(graph.get(chain[-1], ())):
            if neighbor not in seen:
                seen.add(neighbor)
                if len(seen) > max_nodes:
                    return
                queue.append((*chain, neighbor))
