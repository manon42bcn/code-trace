"""Offline inventory and evidence-ranked *candidate* Behave context links.

Never executes project code. Matching a key does not establish runtime flow.
"""

from __future__ import annotations

import ast
import re
import string
import textwrap
from collections import Counter, defaultdict

from .execution_paths import call_graph, reachable
from .hook_scope import scoped_environments
from .python_parsing import parse_python
from .storage_provenance import assess_reference


def _context_key(node):
    """Return (namespace, key) for statically identifiable context access.

    Toolium's CONTEXT resolver prefers storage/ChainMap and falls back to the
    Behave context attribute. These namespaces must not be conflated.
    """
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == 'context':
            return ('behave.context', node.attr)
        if (
            isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == 'context'
            and node.value.attr in ('storage', 'run_storage', 'feature_storage')
        ):
            return ('toolium.' + node.value.attr, node.attr)
    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            if isinstance(node.value, ast.Name) and node.value.id == 'context':
                return ('behave.context', node.slice.value)
            if (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == 'context'
                and node.value.attr in ('storage', 'run_storage', 'feature_storage')
            ):
                return ('toolium.' + node.value.attr, node.slice.value)
    return None


def _initial_key(key):
    # Dotted Toolium references traverse the initial stored value, not a
    # top-level storage key containing literal dots.
    return key.split('.', 1)[0]


def _static_value(node):
    if isinstance(node, ast.Constant) and isinstance(
        node.value, (str, int, float, bool, type(None))
    ):
        return node.value
    return None


def _scope(path):
    parts = path.split('/')
    # A nested steps/ directory is associated with the sibling feature tree.
    if 'steps' in parts:
        n = parts.index('steps')
        if n and parts[n - 1] == 'features':
            return '/'.join(parts[:n])
        if 'features' in parts[:n]:
            return '/'.join(parts[:n])
    if 'features' in parts:
        return '/'.join(parts[: parts.index('features') + 1])
    return None


def _walk_accesses(tree):
    """Use AST expression context, not ast.walk(assign) pretending LHS is a read."""
    for node in ast.walk(tree):
        result = _context_key(node)
        if result is not None:
            namespace, key = result
            kind = (
                'write'
                if isinstance(node.ctx, ast.Store)
                else 'read_write'
                if isinstance(node.ctx, (ast.Del,))
                else 'read'
            )
            yield node, namespace, key, kind


def context_inventory(index, repository):
    producers, consumers, maps = [], [], []
    for chunk in index.get('chunks', []):
        if chunk.get('language') != 'python' or chunk.get('strategy') != 'python_ast':
            continue
        try:
            tree = parse_python(textwrap.dedent(chunk.get('content', '')), quiet=True)
        except (SyntaxError, ValueError):
            continue
        origin = {
            'repository': repository,
            'chunk_id': chunk['id'],
            'path': chunk['path'],
            'symbol': chunk.get('symbol'),
        }
        write_values = {}
        parent = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

        def control_flow_info(node, parent=parent):
            current = parent.get(node)
            while current is not None:
                if isinstance(current, ast.If):
                    branch = (
                        'body' if any(node in ast.walk(item) for item in current.body) else 'orelse'
                    )
                    return 'conditional', 'if', branch
                if isinstance(current, (ast.For, ast.AsyncFor, ast.While)):
                    return 'conditional', 'loop', 'potentially_empty'
                if isinstance(current, ast.Try):
                    if any(node in ast.walk(item) for item in current.finalbody):
                        return 'finally', 'try', 'finally'
                    if any(node in ast.walk(item) for item in current.handlers):
                        return 'conditional', 'exception', 'except_handler'
                    if any(node in ast.walk(item) for item in current.orelse):
                        return 'conditional', 'exception', 'try_else'
                    return 'conditional', 'exception', 'try_body'
                if isinstance(current, (ast.With, ast.AsyncWith)):
                    return 'conditional', 'with', 'body'
                current = parent.get(current)
            return 'unconditional', None, None

        # Explicit writes and augmented assignments; collect original RHS as evidence.
        for n in ast.walk(tree):
            targets = []
            if isinstance(n, ast.Assign):
                targets = n.targets
                rhs = n.value
            elif isinstance(n, ast.AnnAssign):
                targets = [n.target]
                rhs = n.value
            elif isinstance(n, ast.AugAssign):
                targets = [n.target]
                rhs = n.value
            else:
                continue
            for target in targets:
                for sub in ast.walk(target):
                    result = _context_key(sub)
                    if result and isinstance(sub.ctx, ast.Store):
                        write_values[(*result, sub.lineno, sub.col_offset)] = rhs
        seen = set()
        for node, namespace, key, access in _walk_accesses(tree):
            loc = (namespace, key, node.lineno, node.col_offset)
            if loc in seen:
                continue
            seen.add(loc)
            line = chunk.get('start_line', 1) + node.lineno - 1
            record = {
                **origin,
                'namespace': namespace,
                'key': key,
                'line_approx': line,
                'operation': access,
                'control_flow': control_flow_info(node)[0],
                'control_flow_kind': control_flow_info(node)[1],
                'control_flow_branch': control_flow_info(node)[2],
            }
            if access == 'write':
                rhs = write_values.get(loc)
                record['value_kind'] = 'literal' if isinstance(rhs, ast.Constant) else 'dynamic'
                (
                    record['control_flow'],
                    record['control_flow_kind'],
                    record['control_flow_branch'],
                ) = control_flow_info(node)
                if isinstance(rhs, ast.Constant):
                    record['literal_value'] = _static_value(rhs)
                producers.append(record)
            elif access == 'read':
                consumers.append(record)
            else:
                consumers.append(record)
        # Toolium's public writer: context.store_key_in_storage(key, value)
        # or dataset.store_key_in_storage(context, key, value).
        # FEATURE/RUN prefixes designate other ChainMap layers.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != 'store_key_in_storage':
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id == 'context':
                args = node.args
            elif (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'dataset'
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == 'context'
            ):
                args = node.args[1:]
            else:
                continue
            if (
                not args
                or not isinstance(args[0], ast.Constant)
                or not isinstance(args[0].value, str)
            ):
                continue
            raw_key = args[0].value.strip('[]')
            namespace = 'toolium.storage'
            if raw_key.startswith('FEATURE:'):
                namespace, raw_key = 'toolium.feature_storage', raw_key[8:]
            elif raw_key.startswith('RUN:'):
                namespace, raw_key = 'toolium.run_storage', raw_key[4:]
            elif ':' in raw_key:
                continue
            if not raw_key:
                continue
            rhs = args[1] if len(args) > 1 else None
            entry = {
                **origin,
                'key': raw_key,
                'namespace': namespace,
                'line_approx': chunk.get('start_line', 1) + node.lineno - 1,
                'operation': 'write',
                'write_via': 'store_key_in_storage',
                'value_kind': 'literal' if isinstance(rhs, ast.Constant) else 'dynamic',
            }
            if isinstance(rhs, ast.Constant):
                entry['literal_value'] = _static_value(rhs)
            producers.append(entry)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'map_param'
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'context'
            ):
                continue
            first = node.args[0] if node.args else None
            maps.append(
                {
                    **origin,
                    'line_approx': chunk.get('start_line', 1) + node.lineno - 1,
                    'argument_keys': sorted(
                        {
                            k[1]
                            for arg in node.args
                            for sub in ast.walk(arg)
                            if (k := _context_key(sub)) is not None
                        }
                    ),
                    'argument_kind': 'literal'
                    if isinstance(first, ast.Constant)
                    else 'variable'
                    if isinstance(first, ast.Name)
                    else 'expression'
                    if first
                    else 'missing',
                    'argument_literal': _static_value(first)
                    if isinstance(first, ast.Constant)
                    else None,
                }
            )
    return producers, consumers, maps


def _rank_producer(producer, relation, definitions):  # noqa: ARG001 - Preserve public callable signature
    if relation:
        for definition in relation.get('definitions', []):
            if (producer['repository'], producer['chunk_id']) == (
                definition.get('repository'),
                definition.get('chunk_id'),
            ):
                return 'matched_step_definition', 'matched_step_definition'
    symbol = producer.get('symbol') or ''
    path = producer['path']
    scope = _scope(path)
    feature = relation.get('feature_path', '') if relation else ''
    if symbol.rsplit('.', 1)[-1] in {
        'before_all',
        'before_feature',
        'before_scenario',
    } and path.endswith('environment.py'):
        if not scope or feature.startswith(scope + '/') or feature == scope:
            return 'hook_candidate', 'hook_name_and_scope'
    if scope and feature and (feature.startswith(scope + '/') or feature == scope):
        return 'same_feature_scope_candidate', 'feature_scope'
    return 'key_only_candidate', 'matching_key_only'


def _scenario_identity(relation):
    # Examples rows are distinct executions, even within the same Scenario Outline.
    return (
        relation.get('feature_path'),
        relation.get('scenario'),
        relation.get('example_row'),
        tuple(sorted((relation.get('example_values') or {}).items())),
    )


def _is_background(relation):
    return str(relation.get('scenario', '')).lower().startswith('background:')


def _previous_step_definitions(relation, relations):
    """Candidate steps only: earlier lines in the same scenario or its Background.

    Do not apply an Examples row to an unrelated row, even in the same outline.
    """
    identity = _scenario_identity(relation)
    path = relation.get('feature_path')
    line = relation.get('line_approx', 0)
    previous = []
    for r in relations:
        if r is relation or r.get('feature_path') != path:
            continue
        if r.get('line_approx', 0) >= line:
            continue
        if _scenario_identity(r) != identity and not _is_background(r):
            continue
        previous.extend((d.get('repository'), d.get('chunk_id')) for d in r.get('definitions', []))
    return set(previous)


def _direct_call_targets(indexes):
    """Conservative same-repository, same-module direct calls by unique function name.

    Do not assert imports, dispatch, closures, or dynamic calls are resolved.
    """
    result = {}
    for repo, index in indexes.items():
        by_path = {}
        for chunk in index.get('chunks', []):
            if chunk.get('language') != 'python' or chunk.get('strategy') != 'python_ast':
                continue
            symbol = chunk.get('symbol') or ''
            if not symbol:
                continue
            by_path.setdefault(chunk['path'], {}).setdefault(symbol.split('.')[-1], []).append(
                chunk
            )
        for _path, names in by_path.items():
            for candidates in names.values():
                for chunk in candidates:
                    try:
                        tree = parse_python(textwrap.dedent(chunk.get('content', '')), quiet=True)
                    except (SyntaxError, ValueError):
                        continue
                    targets = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                            matching = names.get(node.func.id, [])
                            if len(matching) == 1 and matching[0]['id'] != chunk['id']:
                                targets.add((repo, matching[0]['id']))
                    if targets:
                        result[(repo, chunk['id'])] = targets
    return result


def _literal_path_status(producer, suffix):
    """Inspect only a known literal object; unknown values are NOT failures."""
    if not suffix:
        return 'not_nested'
    if producer.get('value_kind') != 'literal':
        return 'unknown_dynamic_value'
    value = producer.get('literal_value')
    for component in suffix:
        if isinstance(value, dict) and component in value:
            value = value[component]
        elif (
            isinstance(value, (list, tuple))
            and component.isdecimal()
            and int(component) < len(value)
        ):
            value = value[int(component)]
        else:
            return 'literal_path_not_found'
    return 'literal_path_supported'


def _route_assessment(candidate, producer, has_stronger_storage, previous_positions):
    """Conservative triage: plausible paths, conditional paths, or key-only evidence.

    A writer later in the same scenario is not proof of an overwrite, because
    the runtime may branch or clear storage. Record potential shadowing only.
    """
    tier = candidate['tier']
    is_prior = tier.startswith('preceding_')
    conditions = []
    if candidate['conditional_fallback']:
        conditions.append('storage_key_must_be_absent')
    if has_stronger_storage:
        conditions.append('higher_priority_storage_may_shadow')
    if candidate['nested_path_status'] in ('unknown_dynamic_value', 'literal_path_not_found'):
        conditions.append(candidate['nested_path_status'])
    if len(previous_positions) > 1 and candidate.get('producer_step_line') is not None:
        if any(line > candidate['producer_step_line'] for line in previous_positions):
            conditions.append('later_prior_step_may_overwrite')
    if producer.get('control_flow') == 'conditional':
        conditions.append('conditional_write_path')
    elif producer.get('control_flow') == 'finally':
        conditions.append('finally_write_path')
    if not is_prior:
        return 'insufficient_evidence', conditions
    return ('conditional_path' if conditions else 'static_path_candidate'), conditions


def _previous_definition_lines(relation, relations):
    """Preserve step chronology for overwrite diagnostics, per scenario/row."""
    if not relation:
        return {}
    identity, path, limit = (
        _scenario_identity(relation),
        relation.get('feature_path'),
        relation.get('line_approx', 0),
    )
    output = {}
    for r in relations:
        if r is relation or r.get('feature_path') != path or r.get('line_approx', 0) >= limit:
            continue
        if _scenario_identity(r) != identity and not _is_background(r):
            continue
        for d in r.get('definitions', []):
            output.setdefault((d.get('repository'), d.get('chunk_id')), []).append(
                r.get('line_approx', 0)
            )
    return output


def _lifecycle_events(indexes):
    """Describe explicit Hook assignments, without assuming hooks were loaded.

    An assignment to context.storage alters the ChainMap view; it does NOT
    necessarily clear the underlying feature/run dicts.
    """
    events = []
    relevant = {'before_all': 'run', 'before_feature': 'feature', 'before_scenario': 'scenario'}
    for repo, index in indexes.items():
        for chunk in index.get('chunks', []):
            symbol = (chunk.get('symbol') or '').rsplit('.', 1)[-1]
            if (
                chunk.get('language') != 'python'
                or chunk.get('strategy') != 'python_ast'
                or symbol not in relevant
                or not chunk.get('path', '').endswith('environment.py')
            ):
                continue
            try:
                tree = parse_python(textwrap.dedent(chunk.get('content', '')), quiet=True)
            except (ValueError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                for target in targets:
                    if not (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == 'context'
                    ):
                        continue
                    attr = target.attr
                    if attr not in ('storage', 'feature_storage', 'run_storage'):
                        continue
                    kind = 'assignment'
                    if isinstance(value, ast.Dict) and not value.keys:
                        kind = 'new_empty_dict'
                    elif (
                        isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Attribute)
                        and value.func.attr == 'ChainMap'
                    ):
                        kind = 'chainmap_rebind'
                    elif (
                        isinstance(value, ast.Attribute)
                        and isinstance(value.value, ast.Name)
                        and value.value.id == 'context'
                    ):
                        kind = 'alias_assignment'
                    events.append(
                        {
                            'repository': repo,
                            'chunk_id': chunk['id'],
                            'path': chunk['path'],
                            'hook': symbol,
                            'scope': relevant[symbol],
                            'attribute': attr,
                            'effect': kind,
                            'line_approx': chunk.get('start_line', 1) + node.lineno - 1,
                            'runtime_verified': False,
                        }
                    )
    # The same dependency is indexed in several relationship files but only once here.
    return sorted(
        events, key=lambda x: (x['repository'], x['path'], x['line_approx'], x['attribute'])
    )


def _temporal_evidence(candidate, relation, relations, producer, prior_lines):  # noqa: ARG001 - Preserve public callable signature
    """Identify witness chronology, not the effective runtime value."""
    line = candidate.get('producer_step_line')
    if line is not None:
        return 'prior_step_witness', []
    if relation is None:
        return 'unknown_no_relation', []
    # A definition may be used later in this same scenario, never a producer
    # for the current read solely by virtue of being in the same feature.
    identity = _scenario_identity(relation)
    later = sorted(
        {
            r.get('line_approx', 0)
            for r in relations
            if r.get('feature_path') == relation.get('feature_path')
            and _scenario_identity(r) == identity
            and r.get('line_approx', 0) > relation.get('line_approx', 0)
            and any(
                (d.get('repository'), d.get('chunk_id'))
                == (producer['repository'], producer['chunk_id'])
                for d in r.get('definitions', [])
            )
        }
    )
    return ('future_step_only' if later else 'not_ordered_in_scenario'), later


def _step_argument_writers(indexes, relations):
    """Bind literal Gherkin step arguments to parameterized storage writes.

    Only resolved definition + exact format-pattern match + AST parameter used
    as a storage key counts. Never infer runtime registration or execution.
    """
    chunks = {
        (repo, c['id']): c
        for repo, idx in indexes.items()
        for c in idx.get('chunks', [])
        if c.get('strategy') == 'python_ast'
    }
    cache = {}
    patterns = {}
    producers = []
    for rel in relations:
        text = rel.get('resolved_text') or rel.get('text') or ''
        for definition in rel.get('definitions', []):
            identity = (definition.get('repository'), definition.get('chunk_id'))
            chunk = chunks.get(identity)
            pattern = definition.get('pattern')
            if not chunk or not isinstance(pattern, str):
                continue
            if identity not in cache:
                names = set()
                tree = _tree_for_step_writer(chunk.get('content', ''))
                if tree:
                    for node in ast.walk(tree):
                        key = _context_key(node)
                        if key is not None:
                            continue  # fixed keys already in normal inventory
                        if (
                            isinstance(node, ast.Subscript)
                            and isinstance(node.ctx, ast.Store)
                            and isinstance(node.slice, ast.Name)
                            and isinstance(node.value, ast.Attribute)
                            and isinstance(node.value.value, ast.Name)
                            and node.value.value.id == 'context'
                            and node.value.attr in ('storage', 'feature_storage', 'run_storage')
                        ):
                            names.add(('toolium.' + node.value.attr, node.slice.id, node.lineno))
                        if (
                            isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == 'store_key_in_storage'
                        ):
                            args = node.args
                            if (
                                isinstance(node.func.value, ast.Name)
                                and node.func.value.id == 'dataset'
                                and args
                            ):
                                args = args[1:]
                            if args and isinstance(args[0], ast.Name):
                                names.add(('toolium.storage', args[0].id, node.lineno))
                cache[identity] = names
            key_params = cache[identity]
            if not key_params:
                continue
            if pattern not in patterns:
                parts = []
                fields = []
                try:
                    for literal, field, _spec, _conversion in string.Formatter().parse(pattern):
                        parts.append(re.escape(literal))
                        if field is not None:
                            if not field.isidentifier() or field in fields:
                                raise ValueError('Unsupported formatter field')
                            fields.append(field)
                            parts.append('(?P<' + field + '>.*?)')
                    patterns[pattern] = re.compile('^' + ''.join(parts) + '$')
                except (ValueError, re.error):
                    patterns[pattern] = None
            regex = patterns[pattern]
            matched = regex.fullmatch(text) if regex else None
            if not matched:
                continue
            for ns, parameter, lineno in sorted(key_params):
                key = matched.groupdict().get(parameter)
                if not key or '[' in key or ']' in key:
                    continue
                producers.append(
                    {
                        'repository': identity[0],
                        'chunk_id': identity[1],
                        'path': chunk['path'],
                        'symbol': chunk.get('symbol'),
                        'namespace': ns,
                        'key': key,
                        'line_approx': chunk.get('start_line', 1) + lineno - 1,
                        'operation': 'write',
                        'value_kind': 'dynamic',
                        'write_via': 'gherkin_bound_storage_parameter',
                        'step_binding': {
                            'source_repository': rel.get('source_repository'),
                            'feature_path': rel.get('feature_path'),
                            'scenario': rel.get('scenario'),
                            'line_approx': rel.get('line_approx'),
                            'example_row': rel.get('example_row'),
                            'example_values': rel.get('example_values'),
                        },
                    }
                )
    return producers


def _tree_for_step_writer(content):
    try:
        return parse_python(textwrap.dedent(content), quiet=True)
    except (SyntaxError, ValueError):
        return None


def _bound_step_compatible(producer, relation):
    binding = producer.get('step_binding')
    if binding is None:
        return True
    if relation is None or binding['feature_path'] != relation.get('feature_path'):
        return False
    if binding['line_approx'] >= relation.get('line_approx', 0):
        return False
    if binding['scenario'] == relation.get('scenario'):
        return binding['example_row'] == relation.get('example_row') and binding[
            'example_values'
        ] == relation.get('example_values')
    return str(binding['scenario']).lower().startswith('background:')


def _propagated_parameter_writers(indexes):
    """Find bounded same-module writes through up to two direct calls."""
    chunks = {
        (repo, c['id']): c
        for repo, idx in indexes.items()
        for c in idx.get('chunks', [])
        if c.get('language') == 'python' and c.get('strategy') == 'python_ast'
    }
    by_name = defaultdict(list)
    trees = {}
    for identity, chunk in chunks.items():
        try:
            trees[identity] = parse_python(textwrap.dedent(chunk.get('content', '')), quiet=True)
        except (SyntaxError, ValueError):
            continue
        by_name[
            (identity[0], chunk['path'], (chunk.get('symbol') or '').rsplit('.', 1)[-1])
        ].append(identity)

    def resolve(caller_id, expression, bindings):  # noqa: ARG001 - Preserve public callable signature
        if isinstance(expression, ast.Name):
            return bindings.get(expression.id)
        if (
            isinstance(expression, ast.Attribute)
            and isinstance(expression.value, ast.Name)
            and expression.value.id == 'context'
            and expression.attr == 'storage'
        ):
            return ('storage',)
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            return expression.value
        return None

    output = []
    seen = set()

    def visit(caller_id, bindings, chain, depth):
        if depth > 2:
            return
        caller = chunks[caller_id]
        tree = trees.get(caller_id)
        if tree is None:
            return
        local_bindings = dict(bindings)
        changed = True
        while changed:
            changed = False
            for assignment in (n for n in ast.walk(tree) if isinstance(n, ast.Assign)):
                if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name):
                    continue
                name = assignment.targets[0].id
                value = resolve(caller_id, assignment.value, local_bindings)
                if value == ('storage',) and local_bindings.get(name) != value:
                    local_bindings[name] = value
                    changed = True
        for call in (
            n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ):
            targets = by_name.get((caller_id[0], caller['path'], call.func.id), [])
            if len(targets) != 1:
                continue
            callee_id = targets[0]
            fn = next(
                (
                    n
                    for n in ast.walk(trees[callee_id])
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ),
                None,
            )
            if fn is None:
                continue
            params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
            next_bindings = {}
            if len(call.args) > len(params) or any(
                keyword.arg is None for keyword in call.keywords
            ):
                continue
            for parameter, argument in zip(params, call.args, strict=False):
                next_bindings[parameter] = resolve(caller_id, argument, local_bindings)
            for keyword in call.keywords:
                if keyword.arg not in params or keyword.arg in next_bindings:
                    next_bindings = None
                    break
                next_bindings[keyword.arg] = resolve(caller_id, keyword.value, bindings)
            if next_bindings is None:
                continue
            for node in ast.walk(trees[callee_id]):
                if (
                    isinstance(node, ast.Subscript)
                    and isinstance(node.ctx, ast.Store)
                    and isinstance(node.value, ast.Name)
                ):
                    storage = next_bindings.get(node.value.id)
                    key_name = node.slice.id if isinstance(node.slice, ast.Name) else None
                    key = next_bindings.get(key_name) if key_name else None
                    if storage == ('storage',) and isinstance(key, str):
                        marker = (callee_id, key, node.lineno)
                        if marker not in seen:
                            seen.add(marker)
                            output.append(
                                {
                                    'repository': callee_id[0],
                                    'chunk_id': callee_id[1],
                                    'path': chunks[callee_id]['path'],
                                    'symbol': chunks[callee_id].get('symbol'),
                                    'namespace': 'toolium.storage',
                                    'key': key,
                                    'line_approx': chunks[callee_id].get('start_line', 1)
                                    + node.lineno
                                    - 1,
                                    'operation': 'write',
                                    'value_kind': 'dynamic',
                                    'write_via': 'propagated_storage_parameter',
                                    'parameter_binding': {
                                        'caller_chunk_id': caller_id[1],
                                        'call_depth': depth + 1,
                                    },
                                }
                            )
            visit(callee_id, next_bindings, (*chain, callee_id), depth + 1)

    for identity in chunks:
        visit(identity, {}, (identity,), 0)
    return output


def context_flow(indexes, references, relations):
    producers, consumers, calls = [], [], []
    for repo, index in indexes.items():
        p, c, m = context_inventory(index, repo)
        producers.extend(p)
        consumers.extend(c)
        calls.extend(m)
    producers.extend(_step_argument_writers(indexes, relations))
    producers.extend(_propagated_parameter_writers(indexes))
    by_key = {}
    for pid, p in enumerate(producers):
        by_key.setdefault((p['namespace'], p['key']), []).append(pid)

    lifecycle = _lifecycle_events(indexes)
    environments = scoped_environments(indexes, relations, lifecycle)
    direct_calls = _direct_call_targets(indexes)
    layer_order = ['scenario', 'feature', 'run']
    graph, _graph_diagnostics = call_graph(indexes)
    route_cache = {}
    # One direct hop is evidence only, never a verified path through Python.
    links = []
    for ri, ref in enumerate(references):
        if ref.get('kind') != 'context':
            continue
        key = ref.get('key', '')
        if '[' in key or ']' in key:
            links.append(
                {
                    'reference_index': ri,
                    'key': key,
                    'status': 'dynamic_context_key',
                    'candidate_producer_ids': [],
                    'candidates': [],
                    'runtime_verified': False,
                }
            )
            continue
        relid = ref.get('relation_index')
        relation = (
            relations[relid] if isinstance(relid, int) and 0 <= relid < len(relations) else None
        )
        scoped_env = (
            environments.get((relation.get('source_repository'), relation.get('feature_path')))
            if relation
            else None
        )
        previous_lines = _previous_definition_lines(relation, relations)
        previous_defs = set(previous_lines)
        previous_callees = (
            set().union(*(direct_calls.get(x, set()) for x in previous_defs))
            if previous_defs
            else set()
        )
        for start in previous_defs:
            if start not in route_cache:
                route_cache[start] = list(reachable(graph, start))
        witness = {}
        for start in sorted(previous_defs):
            for chain in route_cache[start]:
                old = witness.get(chain[-1])
                if old is None or len(chain) < len(old):
                    witness[chain[-1]] = chain
        candidates = []
        initial_key = _initial_key(key)
        nested_suffix = key.split('.')[1:]
        # Lookup precedence mirrors Toolium's _get_initial_value_from_context:
        # context.storage (a ChainMap spanning feature/run storage), then the
        # Behave context object. A fallback is conditional on key absence.
        prioritized = [
            ('toolium.storage', 'storage_primary'),
            ('toolium.feature_storage', 'storage_feature_layer'),
            ('toolium.run_storage', 'storage_run_layer'),
            ('behave.context', 'behave_attribute_fallback'),
        ]
        matching = [
            (pid, ns, rule) for ns, rule in prioritized for pid in by_key.get((ns, initial_key), [])
        ]
        for pid, namespace, lookup_rule in matching:
            producer = producers[pid]
            if not _bound_step_compatible(producer, relation):
                continue
            identity = (producer['repository'], producer['chunk_id'])
            path = witness.get(identity)
            binding = producer.get('parameter_binding')
            if path is None and binding:
                caller = (producer['repository'], binding['caller_chunk_id'])
                if caller in previous_defs:
                    path = (caller, identity)
            if producer.get('step_binding') is not None:
                tier, evidence = (
                    'preceding_scenario_step_candidate',
                    'gherkin_parameter_bound_to_storage_write',
                )
            elif path and len(path) == 1:
                tier, evidence = (
                    'preceding_scenario_step_candidate',
                    'prior_step_definition_same_scenario_or_background',
                )
            elif path and len(path) > 1:
                tier, evidence = (
                    'preceding_direct_call_candidate',
                    'static_python_call_path_from_prior_step',
                )
            elif identity in previous_callees:
                tier, evidence = (
                    'preceding_direct_call_candidate',
                    'one_hop_direct_call_from_prior_step',
                )
            else:
                tier, evidence = _rank_producer(producer, relation, None)
            prior_lines = [
                line
                for start, lines in previous_lines.items()
                if (
                    start == identity
                    or (path and start == path[0])
                    or identity in direct_calls.get(start, set())
                )
                for line in lines
            ]
            candidate = {
                'producer_id': pid,
                'tier': tier,
                'evidence': evidence,
                'namespace': namespace,
                'lookup_rule': lookup_rule,
                'conditional_fallback': namespace == 'behave.context',
                'runtime_verified': False,
                'storage_layer': namespace,
                'nested_path_status': _literal_path_status(producer, nested_suffix),
            }
            if producer.get('step_binding') is not None:
                candidate['producer_step_line'] = producer['step_binding']['line_approx']
                candidate['step_argument_binding'] = True
            elif prior_lines:
                candidate['producer_step_line'] = max(prior_lines)
            if path:
                candidate['witness_path'] = [{'repository': r, 'chunk_id': c} for r, c in path]
                candidate['call_depth'] = len(path) - 1
            temporal, future_lines = _temporal_evidence(
                candidate, relation, relations, producer, prior_lines
            )
            candidate['temporal_evidence'] = temporal
            if future_lines:
                candidate['future_step_lines'] = future_lines
            candidates.append(candidate)
        # Assess shadowing only between writers with a static preceding-step
        # witness in this scenario. Distinct writes in the same function are
        # not ordered by step line and must not be labelled as overwrites.
        step_positions = {}
        for c in candidates:
            if c.get('producer_step_line') is not None and c['tier'].startswith('preceding_'):
                step_positions.setdefault(c['namespace'], []).append(c['producer_step_line'])
        for c in candidates:
            later = sorted(
                {
                    line
                    for line in step_positions.get(c['namespace'], [])
                    if c.get('producer_step_line') is not None and line > c['producer_step_line']
                }
            )
            c['later_prior_writer_step_lines'] = later
            c['latest_known_prior_writer'] = c.get('producer_step_line') is not None and not later
            p = producers[c['producer_id']]
            # When a higher-priority namespace has a candidate writer, that
            # writer may or may not have run: this is only a warning.
            priority = {
                'toolium.storage': 0,
                'toolium.feature_storage': 1,
                'toolium.run_storage': 2,
                'behave.context': 3,
            }
            stronger = any(priority[x['namespace']] < priority[c['namespace']] for x in candidates)
            c['route_classification'], c['route_conditions'] = _route_assessment(
                c, p, stronger, step_positions.get(c['namespace'], [])
            )
        # Static applicability, never a guarantee about executed hooks or values.
        # A ChainMap rebind creates a fresh scenario map while preserving the
        # feature/run dictionaries; a missing hook witness leaves the model unknown.
        lifecycle_by_hook = {}
        for event in (scoped_env or {}).get('lifecycle_events', []):
            lifecycle_by_hook.setdefault(event['hook'], []).append(event)
        relevant_scenario = any(
            e.get('attribute') == 'storage' and e.get('effect') == 'chainmap_rebind'
            for e in lifecycle_by_hook.get('before_scenario', [])
        )
        relevant_feature = any(
            e.get('attribute') == 'feature_storage' and e.get('effect') == 'new_empty_dict'
            for e in lifecycle_by_hook.get('before_feature', [])
        )
        relevant_run = any(
            e.get('attribute') == 'run_storage' and e.get('effect') == 'new_empty_dict'
            for e in lifecycle_by_hook.get('before_all', [])
        )
        effective_scope = {
            'model': 'conditional_chainmap_static',
            'layer_order': [*layer_order, 'behave.context'],
            'scenario_layer_reachable': relevant_scenario,
            'feature_layer_reachable': relevant_feature,
            'run_layer_reachable': relevant_run,
            'execution_guaranteed': False,
            'runtime_verified': False,
        }
        for candidate in candidates:
            ns = candidate['namespace']
            known_layer = {
                'toolium.feature_storage': 'feature',
                'toolium.run_storage': 'run',
                'behave.context': 'behave.context',
            }.get(ns)
            # context.storage writes normally land in ChainMap.maps[0].
            # Without the hook, maps[0] cannot be assigned to a scenario scope.
            if ns == 'toolium.storage':
                known_layer = 'scenario' if relevant_scenario else 'unknown_storage_view'
            candidate['effective_layer_candidate'] = known_layer
            candidate['layer_applicability'] = (
                'static_hook_reachable'
                if (known_layer == 'scenario' and relevant_scenario)
                or (known_layer == 'feature' and relevant_feature)
                or (known_layer == 'run' and relevant_run)
                else 'hook_not_established'
                if known_layer != 'behave.context'
                else 'fallback_only'
            )
            candidate['effective_value_confirmed'] = False
        provenance = assess_reference(candidates, producers, effective_scope)
        ordering = {
            'preceding_scenario_step_candidate': 0,
            'preceding_direct_call_candidate': 1,
            'matched_step_definition': 2,
            'hook_candidate': 3,
            'same_feature_scope_candidate': 4,
            'key_only_candidate': 5,
        }
        candidates.sort(
            key=lambda e: (
                next(i for i, (ns, _) in enumerate(prioritized) if ns == e['namespace']),
                ordering[e['tier']],
                e['producer_id'],
            )
        )
        blockers = []
        if relation is None:
            blockers.append('no_gherkin_relation')
        elif not previous_defs:
            preceding = [
                r
                for r in relations
                if r is not relation
                and r.get('feature_path') == relation.get('feature_path')
                and r.get('line_approx', 0) < relation.get('line_approx', 0)
                and (_scenario_identity(r) == _scenario_identity(relation) or _is_background(r))
            ]
            blockers.append(
                'prior_steps_without_matched_definition'
                if preceding
                else 'no_prior_steps_in_scenario'
            )
        if not candidates:
            blockers.append('no_static_writer_for_key')
        elif not any(c['tier'].startswith('preceding_') for c in candidates):
            blockers.append('no_reachable_writer_from_prior_step')
        links.append(
            {
                'reference_index': ri,
                'key': key,
                'status': 'candidate_producers' if candidates else 'no_static_producer_found',
                'environment_scope_ref': {
                    'repository': relation.get('source_repository'),
                    'feature_path': relation.get('feature_path'),
                }
                if scoped_env
                else None,
                'entry_environment': scoped_env['entry_environment'] if scoped_env else None,
                'hook_applicability': scoped_env['status'] if scoped_env else 'unknown_no_relation',
                'candidate_hook_lifecycle_events': len(scoped_env['lifecycle_events'])
                if scoped_env
                else 0,
                'static_execution_phases': [
                    'before_all',
                    'before_feature',
                    'before_scenario',
                    'background',
                    'scenario_steps',
                ],
                'lookup_order': [
                    'toolium.storage',
                    'toolium.feature_storage',
                    'toolium.run_storage',
                    'behave.context',
                ],
                'effective_storage_scope': effective_scope,
                'candidate_provenance': provenance,
                'lookup_key': initial_key,
                'nested_segments': nested_suffix,
                'resolution_model': 'ordered_candidate_layers_not_effective_runtime_value',
                'candidate_producer_ids': [c['producer_id'] for c in candidates],
                'candidates': candidates,
                'diagnostics': blockers,
                'runtime_verified': False,
            }
        )
    by_chunk = {}
    for i, call in enumerate(calls):
        by_chunk.setdefault((call['repository'], call['chunk_id']), []).append(i)
    mapped = []
    for i, rel in enumerate(relations):
        ids = sorted(
            {
                cid
                for d in rel.get('definitions', [])
                for cid in by_chunk.get((d['repository'], d['chunk_id']), [])
            }
        )
        if ids:
            mapped.append(
                {'relation_index': i, 'map_param_call_ids': ids, 'runtime_verified': False}
            )
    tiers = Counter(c['tier'] for link in links for c in link.get('candidates', []))
    route_classes = Counter(
        c['route_classification'] for link in links for c in link.get('candidates', [])
    )
    temporal_counts = Counter(
        c['temporal_evidence'] for link in links for c in link.get('candidates', [])
    )
    route_conditions = Counter(
        reason
        for link in links
        for c in link.get('candidates', [])
        for reason in c['route_conditions']
    )
    unique_candidate_evidence = {
        (
            link.get('reference_index'),
            link.get('key'),
            c.get('producer_id'),
            c.get('tier'),
            tuple(
                (step.get('repository'), step.get('chunk_id')) for step in c.get('witness_path', [])
            ),
        )
        for link in links
        for c in link.get('candidates', [])
    }
    unique_calls = {(c['repository'], c['chunk_id'], c['line_approx']) for c in calls}
    unique_definitions = {
        (d['repository'], d['chunk_id']) for r in relations for d in r.get('definitions', [])
    }
    return {
        'producers': producers,
        'consumers': consumers,
        'map_param_calls_ast': calls,
        'reference_producer_links': links,
        'step_map_param_links': mapped,
        'storage_lifecycle': lifecycle,
        'scoped_environments': [
            {'repository': repo, 'feature_path': path, **env}
            for (repo, path), env in sorted(environments.items())
        ],
        'summary': {
            'producers': len(producers),
            'consumers': len(consumers),
            'map_param_calls_ast': len(calls),
            'unique_map_param_calls': len(unique_calls),
            'unique_matched_step_definitions': len(unique_definitions),
            'step_map_param_occurrences': len(mapped),
            'candidate_tiers': dict(tiers),
            'route_classifications': dict(route_classes),
            'temporal_evidence': dict(temporal_counts),
            'hook_storage_assignments': len(lifecycle),
            'feature_scopes_analyzed': len(environments),
            'feature_scopes_with_hook_candidates': sum(
                bool(e['hooks']) for e in environments.values()
            ),
            'feature_scopes_without_environment': sum(
                e['entry_environment'] is None for e in environments.values()
            ),
            'route_conditions': dict(route_conditions),
            'witness_paths': sum(
                any(c.get('witness_path') for c in link.get('candidates', [])) for link in links
            ),
            'candidate_evidence_records': sum(len(link.get('candidates', [])) for link in links),
            'unique_candidate_evidence_records': len(unique_candidate_evidence),
            'duplicate_candidate_evidence_records': sum(
                len(link.get('candidates', [])) for link in links
            )
            - len(unique_candidate_evidence),
            'diagnostic_reasons': dict(
                Counter(reason for link in links for reason in link.get('diagnostics', []))
            ),
            'references_with_candidates': sum(e['status'] == 'candidate_producers' for e in links),
            'references_without_candidates': sum(
                e['status'] == 'no_static_producer_found' for e in links
            ),
        },
        'disclaimer': (
            'La cronología procede de las líneas Gherkin y de rutas AST '
            'candidatas; los hooks detectados no se presuponen cargados. Una '
            'reasignación ChainMap no implica borrar feature/run storage. Las '
            'condiciones de precedencia y sobrescritura son estáticas; no '
            'identifican el valor runtime. CONTEXT consulta primero '
            'context.storage/ChainMap y recurre a un atributo del contexto '
            'Behave solo si falta la clave inicial. Los candidatos no prueban '
            'qué valor prevalece en runtime.'
        ),
    }
