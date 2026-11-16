"""Bounded static call-flow evidence; never a runtime trace or framework dispatch order."""

import ast
import re
import textwrap
import unicodedata
from collections import deque

from .python_parsing import parse_python

HTTP_METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE'}
FLOW_LIMITATIONS = [
    'Static call edges indicate possible reachability, not execution order or a runtime trace.',
    'Recognized FastAPI/Flask decorators are candidate application handlers; '
    'router mounting, prefixes, middleware, '
    'dependencies and server dispatch are not resolved.',
    'Only indexed Python symbols and locally available unique static call targets are followed; '
    'dynamic dispatch and other languages may be missing.',
]


def normalized(query):
    return ''.join(
        c for c in unicodedata.normalize('NFKD', query.casefold()) if not unicodedata.combining(c)
    )


def is_flow_query(query):
    text = normalized(query)
    return bool(
        re.search(r'\b(flujo|flow|entrypoint|entry point|punto de entrada|call chain)\b', text)
        or re.search(r'\b(primera? funcion|first function|first handler)\b', text)
        or (
            re.search(r'\b(peticion|request|endpoint|solicitud)\b', text)
            and re.search(
                r'\b(llega|llegar|recibe|recibir|atiende|handles|receives|handled)\b', text
            )
        )
    )


def _http_question(query):
    return bool(
        re.search(r'\b(http|peticion|request|endpoint|solicitud|handler)\b', normalized(query))
        or re.search(r'\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/', query)
    )


def _http_receivers(index):
    """Resolve explicit FastAPI/Flask constructor bindings and local router imports."""
    modules = {}
    packages = {}
    constructors = {'fastapi.FastAPI', 'fastapi.APIRouter', 'flask.Flask', 'flask.Blueprint'}
    receivers = set()
    for chunk in index.get('chunks', []):
        if chunk.get('language') != 'python' or chunk.get('symbol'):
            continue
        try:
            tree = parse_python(chunk.get('content', ''), quiet=True)
        except (SyntaxError, ValueError):
            continue
        module = chunk['path'].removesuffix('.py').replace('/', '.').removesuffix('.__init__')
        modules.setdefault(module, []).extend(tree.body)
        packages[module] = (
            module.split('.') if chunk['path'].endswith('/__init__.py') else module.split('.')[:-1]
        )
    bindings = {}
    for module, body in modules.items():
        names = bindings.setdefault(module, {})
        for node in body:
            if isinstance(node, ast.ImportFrom):
                package = packages[module]
                if node.level and node.level - 1 > len(package):
                    continue
                prefix = package[: len(package) - node.level + 1] if node.level else []
                imported = '.'.join([*prefix, *([node.module] if node.module else [])])
                for alias in node.names:
                    names[alias.asname or alias.name] = imported + '.' + alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names[alias.asname or alias.name.split('.')[0]] = alias.name
    for module, body in modules.items():
        names = bindings[module]
        for node in body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            function = value.func
            qualified = None
            if isinstance(function, ast.Name):
                qualified = names.get(function.id)
            elif isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
                qualified = names.get(function.value.id, '') + '.' + function.attr
            if qualified in constructors:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        receivers.add(module + '.' + target.id)
    # Imported router aliases can cross a few re-export modules; never execute imports.
    for _ in range(4):
        extra = {
            module + '.' + alias
            for module, names in bindings.items()
            for alias, target in names.items()
            if target in receivers
        }
        if extra <= receivers:
            break
        receivers |= extra
    return receivers


def _routes(index):
    """Recognize literal Python HTTP-style decorators without assuming router registration."""
    found = []
    seen = set()
    receivers = _http_receivers(index)
    for chunk in index.get('chunks', []):
        content = chunk.get('content', '')
        if chunk.get('language') != 'python' or '@' not in content:
            continue
        if not re.search(
            r'\.(get|post|put|patch|delete|head|options|trace|route|api_route)\s*\(', content
        ):
            continue
        try:
            tree = parse_python(textwrap.dedent(content), quiet=True)
        except (SyntaxError, ValueError):
            continue
        for function in tree.body:
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in function.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(
                    decorator.func, ast.Attribute
                ):
                    continue
                receiver = decorator.func.value
                module = (
                    chunk['path'].removesuffix('.py').replace('/', '.').removesuffix('.__init__')
                )
                if (
                    not isinstance(receiver, ast.Name)
                    or module + '.' + receiver.id not in receivers
                ):
                    continue
                method = decorator.func.attr.upper()
                if method not in HTTP_METHODS | {'ROUTE', 'API_ROUTE'}:
                    continue
                path = (
                    decorator.args[0]
                    if decorator.args
                    else next(
                        (k.value for k in decorator.keywords if k.arg in {'path', 'rule'}), None
                    )
                )
                if not isinstance(path, ast.Constant) or not isinstance(path.value, str):
                    continue
                if not path.value.startswith('/'):
                    continue
                methods = [method] if method in HTTP_METHODS else ['UNSPECIFIED']
                declared = next((k.value for k in decorator.keywords if k.arg == 'methods'), None)
                if isinstance(declared, (ast.List, ast.Tuple)) and all(
                    isinstance(v, ast.Constant) and isinstance(v.value, str) for v in declared.elts
                ):
                    methods = [v.value.upper() for v in declared.elts]
                key = (chunk['id'], path.value, tuple(methods))
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    {
                        'chunk_id': chunk['id'],
                        'symbol': chunk.get('symbol') or function.name,
                        'path': chunk.get('path'),
                        'route': path.value,
                        'methods': methods,
                        'kind': 'http_decorator_candidate',
                        'runtime_verified': False,
                    }
                )
    return sorted(found, key=lambda r: (r['path'], r['symbol'], r['route'], r['methods']))


def _calls(index, graph):
    chunks = {c['id'] for c in index.get('chunks', [])}
    nodes = {n['id']: n for n in graph.get('nodes', [])}
    calls = {}
    for edge in graph.get('edges', []):
        if edge.get('type') != 'calls' or edge.get('evidence') != 'static_unique_call_target':
            continue
        source = nodes.get(edge.get('source'), {}).get('chunk_id')
        target = nodes.get(edge.get('target'), {}).get('chunk_id')
        if source in chunks and target in chunks:
            calls.setdefault(source, set()).add(target)
    return calls


def flow_candidates(index, graph, query, results, *, max_roots=5, max_nodes=40, max_depth=4):
    """Put entry evidence before lexical matches; all excerpts still pass normal context budgets."""
    chunks = {c['id']: c for c in index.get('chunks', [])}
    routes = _routes(index) if _http_question(query) else []
    paths = re.findall(r'(?<![\w:])(/[\w{}./:-]*)', query)
    methods = [word for word in re.findall(r'\b[A-Z]+\b', query) if word in HTTP_METHODS]
    matches = [
        r
        for r in routes
        if (not paths or r['route'] in paths)
        and (
            not methods or set(methods).intersection(r['methods']) or 'UNSPECIFIED' in r['methods']
        )
    ]
    if _http_question(query):
        roots = matches
    else:
        # Generic flows start from retrieved Python functions, not arbitrary configuration values.
        start = re.search(
            r"(?:from|desde|starting at|a partir de|flujo de|flow of)\s+[`\"']?"
            r'([A-Za-z_]\w*(?:\.\w+)*)',
            query,
            re.IGNORECASE,
        )
        seeds = results
        if start:
            seeds = [{'chunk_id': c['id']} for c in chunks.values() if c.get('symbol') == start[1]]
        roots = [
            {
                'chunk_id': r['chunk_id'],
                'symbol': chunks[r['chunk_id']].get('symbol'),
                'path': chunks[r['chunk_id']].get('path'),
                'kind': 'retrieved_symbol',
                'runtime_verified': False,
            }
            for r in seeds
            if r.get('chunk_id') in chunks
            and chunks[r['chunk_id']].get('language') == 'python'
            and chunks[r['chunk_id']].get('strategy') == 'python_ast'
            and chunks[r['chunk_id']].get('symbol')
        ]
    root_map = {}
    for root in roots:
        root_map.setdefault(root['chunk_id'], root)
    roots = list(root_map.values())
    unique_roots = list(root_map)
    root_limit = min(max_roots, max_nodes)
    queue = deque((root, 0) for root in unique_roots[:root_limit])
    ordered = []
    seen = set()
    edges = []
    scheduled = set(unique_roots[:root_limit])
    traversal_truncated = len(unique_roots) > root_limit
    calls = _calls(index, graph)
    while queue and len(ordered) < max_nodes:
        source, depth = queue.popleft()
        if source in seen:
            continue
        seen.add(source)
        ordered.append(source)
        if depth >= max_depth:
            traversal_truncated |= bool(calls.get(source))
            continue
        for target in sorted(calls.get(source, ())):
            if target not in scheduled:
                if len(scheduled) >= max_nodes:
                    traversal_truncated = True
                    continue
                scheduled.add(target)
                queue.append((target, depth + 1))
            edges.append(
                {'source': source, 'target': target, 'type': 'calls', 'runtime_verified': False}
            )
    evidence = [
        {'chunk_id': chunk_id, 'score': 1.0, 'source': 'static-code-flow'} for chunk_id in ordered
    ]
    remainder = [r for r in results if r.get('chunk_id') not in seen]
    return evidence + remainder, {
        'kind': 'static_call_flow',
        'http_question': _http_question(query),
        'recognized_http_candidates': len(routes),
        'matching_entry_candidates': len(unique_roots),
        'ambiguous_entry': len(unique_roots) > 1,
        'entries': roots[:max_roots],
        'edges': edges,
        'max_depth': max_depth,
        'max_nodes': max_nodes,
        'max_roots': max_roots,
        'candidate_nodes': len(ordered),
        'traversal_truncated': traversal_truncated,
        'limitations': FLOW_LIMITATIONS,
    }


def selected_flow(flow, context):
    """Only expose relationships whose endpoints have actually been supplied to the model."""
    selected = {item['citation']['chunk_id'] for item in context.get('items', [])}
    return {
        **flow,
        'entries': [entry for entry in flow['entries'] if entry['chunk_id'] in selected],
        'edges': [
            edge
            for edge in flow['edges']
            if edge['source'] in selected and edge['target'] in selected
        ],
        'selected_nodes': len(
            selected.intersection(
                {e['chunk_id'] for e in flow['entries']}
                | {e[k] for e in flow['edges'] for k in ('source', 'target')}
            )
        ),
        'scope': 'Only edges between supplied evidence snippets; bounded and possibly incomplete.',
    }
