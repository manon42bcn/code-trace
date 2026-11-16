"""Conservative per-feature Behave hook applicability through explicit imports.

No repository code is imported or executed. A static delegation is not proof that
Behave loads the selected environment module at runtime.
"""

from __future__ import annotations

import ast
import textwrap
from collections import defaultdict

from .python_parsing import parse_python

HOOKS = ('before_all', 'before_feature', 'before_scenario')


def _parsed(src):
    try:
        return parse_python(textwrap.dedent(src), quiet=True)
    except (ValueError, SyntaxError):
        return None


def _module_name(path):
    return path.removesuffix('.py').replace('/', '.')


def _catalog(indexes):
    modules = defaultdict(list)
    imports = defaultdict(dict)
    stars = defaultdict(list)
    methods = {}
    for repo, idx in indexes.items():
        for c in idx.get('chunks', []):
            if c.get('language') != 'python':
                continue
            path = c['path']
            mod = _module_name(path)
            if path.endswith('/__init__.py'):
                mod = _module_name(path[:-12])
            modules[mod].append((repo, path))
            tree = _parsed(c.get('content', ''))
            if tree is None:
                continue
            if c.get('strategy') == 'python_ast' and c.get('symbol') and '.' not in c['symbol']:
                methods[(repo, path, c['symbol'])] = c
            for n in ast.walk(tree):
                # Avoid imports local to a function: only module-level imports
                # are static registration evidence for the entry environment.
                if n not in tree.body:
                    continue
                if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    for a in n.names:
                        if a.name == '*':
                            stars[(repo, path)].append(n.module)
                        else:
                            imports[(repo, path)][a.asname or a.name] = (n.module, a.name)
    return modules, imports, stars, methods


def environment_scope(indexes, feature_path, repository, lifecycle=(), catalog=None):
    """Choose the closest environment.py in the feature's ancestor directories.

    Resolve only explicit imports, unambiguous star reexports and direct named
    calls. Never infer hooks merely because Toolium is an indexed dependency.
    """
    modules, imports, stars, methods = catalog if catalog is not None else _catalog(indexes)
    candidates = []
    for c in indexes.get(repository, {}).get('chunks', []):
        path = c.get('path', '')
        if not path.endswith('/environment.py'):
            continue
        prefix = path[: -len('environment.py')]
        if feature_path.startswith(prefix) and path != feature_path:
            candidates.append(path)
    if not candidates:
        return {
            'entry_environment': None,
            'status': 'no_environment_in_feature_ancestors',
            'hooks': [],
            'lifecycle_events': [],
            'runtime_verified': False,
        }
    entry = max(set(candidates), key=lambda x: len(x))

    def resolve_module(module, prefer_repo):
        exact = set(modules.get(module, []))
        if len(exact) == 1:
            return next(iter(exact))
        if exact:
            return None
        suffix = '.' + module
        alternatives = {
            (r, p)
            for m, values in modules.items()
            if m.endswith(suffix)
            for r, p in values
            if r == prefer_repo
        }
        return next(iter(alternatives)) if len(alternatives) == 1 else None

    def direct_calls(chunk):
        """Collect named calls; mark structural uncertainty (branches, decorators)."""
        tree = _parsed(chunk.get('content', ''))
        if not tree:
            return []
        functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not functions:
            return []
        fn = functions[0]
        decorated = bool(fn.decorator_list)
        found_calls = []

        def visit(node, conditional=False):
            # Do not interpret nested functions as unconditional calls.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                return
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                found_calls.append(
                    (
                        node.func.id,
                        conditional or decorated,
                        ['decorated_helper'] if decorated else [],
                    )
                )
            uncertain = isinstance(
                node,
                (
                    ast.If,
                    ast.Try,
                    ast.TryStar,
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.With,
                    ast.AsyncWith,
                    ast.Match,
                ),
            )
            for child in ast.iter_child_nodes(node):
                visit(child, conditional or uncertain)

        for statement in fn.body:
            visit(statement)
        return found_calls

    traces = []
    all_events = []
    target_sites = {(e['repository'], e['path'], e['hook']) for e in lifecycle}
    trace_stats = {'visited_nodes': 0, 'relevant_targets': 0, 'suppressed_non_storage_paths': 0}
    for hook in HOOKS:
        visited = set()
        queue = [(repository, entry, hook, [], [], False)]
        found = []
        while queue:
            repo, path, name, chain, conditions, uncertain = queue.pop(0)
            if (repo, path, name) in visited or len(chain) >= 8:
                continue
            visited.add((repo, path, name))
            trace_stats['visited_nodes'] += 1
            here = {'repository': repo, 'path': path, 'hook': name}
            new_chain = [*chain, here]
            chunk = methods.get((repo, path, name))
            if chunk:
                if (repo, path, name) in target_sites or (not lifecycle and name == hook):
                    found.append(
                        {
                            'chain': new_chain,
                            'evidence': 'storage_lifecycle_target',
                            'conditions': sorted(set(conditions)),
                            'reachability': 'conditional_static'
                            if uncertain
                            else 'static_reachable',
                            'runtime_verified': False,
                        }
                    )
                else:
                    trace_stats['suppressed_non_storage_paths'] += 1
                for called, is_conditional, flags in direct_calls(chunk):
                    binding = imports[(repo, path)].get(called)
                    next_conditions = (
                        conditions
                        + flags
                        + (['conditional_control_flow'] if is_conditional and not flags else [])
                    )
                    if binding:
                        target = resolve_module(binding[0], repo)
                        if target:
                            r, p = target
                            if (r, p, binding[1]) in methods:
                                queue.append(
                                    (
                                        r,
                                        p,
                                        binding[1],
                                        new_chain,
                                        next_conditions,
                                        uncertain or is_conditional,
                                    )
                                )
                    elif (repo, path, called) in methods:
                        queue.append(
                            (
                                repo,
                                path,
                                called,
                                new_chain,
                                next_conditions,
                                uncertain or is_conditional,
                            )
                        )
            else:
                # Resolve a reexport, including AICC's `from common.environment import *`.
                binding = imports[(repo, path)].get(name)
                mods = [binding[0]] if binding and binding[1] == name else stars[(repo, path)]
                for mod in mods:
                    target = resolve_module(mod, repo)
                    if target:
                        r, p = target
                        queue.append(
                            (
                                r,
                                p,
                                binding[1] if binding else name,
                                new_chain,
                                conditions,
                                uncertain,
                            )
                        )
        # Preserve a single shortest witness per lifecycle destination. Conditional
        # alternatives remain summarized, not duplicated in the JSON.
        best = {}
        for match in found:
            end = match['chain'][-1]
            dest = (end['repository'], end['path'], end['hook'])
            if dest not in best or (len(match['chain']), len(match['conditions'])) < (
                len(best[dest]['chain']),
                len(best[dest]['conditions']),
            ):
                best[dest] = match
        trace_stats['relevant_targets'] += len(best)
        for match in best.values():
            traces.append({'hook': hook, **match})
            for event in lifecycle:
                end = match['chain'][-1]
                if (event['repository'], event['path'], event['hook']) == (
                    end['repository'],
                    end['path'],
                    end['hook'],
                ):
                    all_events.append(
                        {
                            **event,
                            'hook_chain': match['chain'],
                            'reachability': match['reachability'],
                            'conditions': match['conditions'],
                            'runtime_verified': False,
                        }
                    )
    # A hook can have several records where it delegates further. Events are
    # provided only for recognized reachable assignment sites, not inferred.
    return {
        'entry_environment': entry,
        'status': 'static_hook_candidates' if traces else 'no_hook_chain_resolved',
        'hooks': traces,
        'lifecycle_events': all_events,
        'trace_stats': trace_stats,
        'runtime_verified': False,
    }


def scoped_environments(indexes, relations, lifecycle):
    result = {}
    catalog = _catalog(indexes)
    for r in relations:
        path = r.get('feature_path')
        repo = r.get('source_repository')
        if path and repo and (repo, path) not in result:
            result[(repo, path)] = environment_scope(
                indexes, path, repo, lifecycle, catalog=catalog
            )
    return result
