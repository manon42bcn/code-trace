import pytest

from coderag.provenance_query import query_provenance


def graph():
    nodes = [{'id': x, 'kind': 'python_symbol'} for x in ('w', 'a', 'r', 'z')]
    nodes += [
        {
            'id': 'key1',
            'kind': 'data_key',
            'repository': 'one',
            'namespace': 'storage',
            'key': 'token',
        },
        {
            'id': 'key2',
            'kind': 'data_key',
            'repository': 'two',
            'namespace': 'storage',
            'key': 'token',
        },
    ]
    edges = [
        {'id': 'e1', 'type': 'writes', 'source': 'w', 'target': 'key1'},
        {'id': 'e2', 'type': 'reads', 'source': 'r', 'target': 'key1'},
        {'id': 'e3', 'type': 'writes', 'source': 'z', 'target': 'key2'},
        {'id': 'e4', 'type': 'reads', 'source': 'r', 'target': 'key2'},
        {'id': 'e5', 'type': 'calls', 'source': 'w', 'target': 'a'},
        {'id': 'e6', 'type': 'calls', 'source': 'a', 'target': 'r'},
        {'id': 'e7', 'type': 'calls', 'source': 'a', 'target': 'w'},
    ]
    return {'source_repository': 'one', 'nodes': nodes, 'edges': edges}


def test_route_and_repository_isolation():
    result = query_provenance(graph(), key='token', namespace='storage', repository='one')
    assert result['summary'] == {
        'candidate_pairs': 1,
        'possible_pairs': 1,
        'truncated_pairs': 0,
        'with_call_path': 1,
        'without_call_path': 0,
    }
    assert result['candidates'][0]['call_path'] == ['w', 'a', 'r']
    assert result['candidates'][0]['runtime_verified'] is False


def test_depth_bounded_and_no_false_disconnection():
    result = query_provenance(graph(), key='token', repository='one', max_depth=1)
    assert result['candidates'][0]['classification'] == 'insufficient_route_evidence'
    assert result['guarantees']['absence_of_static_path_implies_no_flow'] is False


def test_pair_cap_and_independent_namespaces():
    g = graph()
    g['edges'].append({'id': 'e8', 'type': 'reads', 'source': 'a', 'target': 'key1'})
    result = query_provenance(g, key='token', repository='one', max_pairs=1)
    assert result['summary']['possible_pairs'] == 2
    assert result['summary']['truncated_pairs'] == 1
    assert query_provenance(g, key='token', namespace='other')['candidates'] == []


def test_invalid_graph_and_limits():
    with pytest.raises(ValueError, match='cadena no vacía'):
        query_provenance(graph(), key='', max_depth=2)
    with pytest.raises(ValueError, match='límites deben ser positivos'):
        query_provenance(graph(), key='token', max_pairs=0)
    g = graph()
    g['edges'][0]['target'] = 'missing'
    with pytest.raises(ValueError, match='referencias a nodos inexistentes'):
        query_provenance(g, key='token')


def test_stable_output():
    assert query_provenance(graph(), key='token') == query_provenance(graph(), key='token')
