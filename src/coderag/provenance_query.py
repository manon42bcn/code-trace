"""Bounded, conservative offline provenance queries over an evidence graph.

A shared data key is a candidate pairing, never a value-flow assertion.
Call routes are syntactic witnesses only, and absence of a route is not proof
of disconnection in dynamic Python.
"""

from __future__ import annotations

from collections import defaultdict, deque


def _routes(adjacency, start, end, max_depth, max_nodes):
    if start == end:
        return [[start]], False
    queue = deque([(start,)])
    seen = {start}
    truncated = False
    while queue:
        path = queue.popleft()
        if len(path) - 1 >= max_depth:
            if adjacency.get(path[-1]):
                truncated = True
            continue
        for target in sorted(adjacency.get(path[-1], ())):
            if target == end:
                return [[*path, target]], truncated
            if target in seen:
                continue
            if len(seen) >= max_nodes:
                truncated = True
                continue
            seen.add(target)
            queue.append((*path, target))
    return [], truncated


def query_provenance(
    graph, *, key, namespace=None, max_depth=4, max_nodes=80, max_pairs=200, repository=None
):
    """Enumerate candidate writer/reader pairings for an exact key and namespace.

    All limits are strict and deterministic. Distinct namespaces and repositories
    never get joined implicitly. No path is a runtime validation.
    """
    if not isinstance(key, str) or not key:
        raise ValueError('La clave --key debe ser una cadena no vacía')
    if max_depth < 0 or max_nodes < 1 or max_pairs < 1:
        raise ValueError('Los límites deben ser positivos (max-depth puede ser 0)')
    nodes = {n['id']: n for n in graph.get('nodes', [])}
    edge_ids = set()
    writers, readers = defaultdict(list), defaultdict(list)
    adjacency = defaultdict(set)
    for edge in graph.get('edges', []):
        if edge.get('source') not in nodes or edge.get('target') not in nodes:
            raise ValueError('El grafo contiene referencias a nodos inexistentes')
        if edge['id'] in edge_ids:
            raise ValueError('El grafo contiene IDs de arista duplicados')
        edge_ids.add(edge['id'])
        kind = edge.get('type')
        if kind == 'calls':
            adjacency[edge['source']].add(edge['target'])
        elif kind in ('writes', 'reads'):
            target = nodes[edge['target']]
            if target.get('kind') != 'data_key':
                continue
            if target.get('key') != key or (
                namespace is not None and target.get('namespace') != namespace
            ):
                continue
            if repository is not None and target.get('repository') != repository:
                continue
            group = (target.get('repository'), target.get('namespace'), target.get('key'))
            (writers if kind == 'writes' else readers)[group].append(edge)
    pairs = []
    possible = sum(len(writers[k]) * len(readers.get(k, [])) for k in writers)
    for group in sorted(set(writers) | set(readers), key=lambda g: tuple(str(x) for x in g)):
        for write in sorted(writers.get(group, []), key=lambda e: e['id']):
            for read in sorted(readers.get(group, []), key=lambda e: e['id']):
                if len(pairs) == max_pairs:
                    break
                forward, f_limited = _routes(
                    adjacency, write['source'], read['source'], max_depth, max_nodes
                )
                reverse, r_limited = _routes(
                    adjacency, read['source'], write['source'], max_depth, max_nodes
                )
                if forward:
                    status = 'static_call_path_writer_to_reader'
                elif reverse:
                    status = 'static_call_path_reader_to_writer'
                else:
                    status = 'insufficient_route_evidence'
                pairs.append(
                    {
                        'repository': group[0],
                        'namespace': group[1],
                        'key': group[2],
                        'writer_node': write['source'],
                        'reader_node': read['source'],
                        'write_edge': write['id'],
                        'read_edge': read['id'],
                        'classification': status,
                        'call_path': forward[0] if forward else (reverse[0] if reverse else []),
                        'call_path_direction': 'writer_to_reader'
                        if forward
                        else ('reader_to_writer' if reverse else None),
                        'search_truncated': f_limited or r_limited,
                        'runtime_verified': False,
                        'limitations': [
                            'same_key_does_not_prove_value_flow',
                            'call_path_does_not_prove_execution',
                            'temporal_order_and_storage_lifetime_not_proven',
                        ],
                    }
                )
            if len(pairs) == max_pairs:
                break
        if len(pairs) == max_pairs:
            break
    return {
        'schema_version': 1,
        'source_repository': graph.get('source_repository'),
        'query': {
            'key': key,
            'namespace': namespace,
            'repository': repository,
            'max_depth': max_depth,
            'max_nodes': max_nodes,
            'max_pairs': max_pairs,
        },
        'summary': {
            'candidate_pairs': len(pairs),
            'possible_pairs': possible,
            'truncated_pairs': max(0, possible - len(pairs)),
            'with_call_path': sum(bool(p['call_path']) for p in pairs),
            'without_call_path': sum(not p['call_path'] for p in pairs),
        },
        'candidates': pairs,
        'guarantees': {
            'runtime_execution_inferred': False,
            'value_provenance_inferred': False,
            'absence_of_static_path_implies_no_flow': False,
        },
    }
