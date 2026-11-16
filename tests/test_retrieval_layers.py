from coderag.hybrid_search import hybrid_search
from coderag.reranking import reciprocal_rank_fusion
from coderag.search import search_hybrid
from coderag.structural_search import search_graph


def test_access_profile_routes_to_edge_filter():
    index = {'chunks': []}
    graph = {
        'nodes': [
            {'id': 'w', 'kind': 'python_symbol', 'chunk_id': 'writer'},
            {'id': 'k', 'kind': 'data_key', 'key': 'order_id'},
        ],
        'edges': [{'source': 'w', 'target': 'k', 'type': 'writes'}],
    }
    assert (
        search_hybrid(index, graph, 'order_id', structural_kind='key', access='writes')[0][
            'chunk_id'
        ]
        == 'writer'
    )


def test_structural_data_key_edge_filters():
    graph = {
        'nodes': [
            {'id': 'w', 'kind': 'python_symbol', 'chunk_id': 'writer'},
            {'id': 'r', 'kind': 'python_symbol', 'chunk_id': 'reader'},
            {'id': 'k', 'kind': 'data_key', 'key': 'order_id'},
        ],
        'edges': [
            {'source': 'w', 'target': 'k', 'type': 'writes'},
            {'source': 'r', 'target': 'k', 'type': 'reads'},
        ],
    }
    assert (
        search_graph(graph, 'order_id', kind='key', edge_type='writes')[0]['chunk_id'] == 'writer'
    )
    assert search_graph(graph, 'order_id', kind='key', edge_type='reads')[0]['chunk_id'] == 'reader'


def test_structural_data_key_links_chunks():
    graph = {
        'nodes': [
            {'id': 's', 'kind': 'python_symbol', 'chunk_id': 'chunk-a'},
            {'id': 'k', 'kind': 'data_key', 'key': 'order_id'},
        ],
        'edges': [{'source': 's', 'target': 'k', 'type': 'writes'}],
    }
    result = search_graph(graph, 'order_id', kind='key')[0]
    assert result['chunk_ids'] == ['chunk-a']
    assert result['chunk_id'] == 'chunk-a'
    assert result['accesses'] == [{'chunk_id': 'chunk-a', 'edge_type': 'writes'}]
    assert result['score'] == 0.8


def test_structural_search_finds_symbol_and_key():
    graph = {
        'nodes': [
            {'id': 's', 'kind': 'python_symbol', 'symbol': 'save_order', 'path': 'src/orders.py'},
            {'id': 'k', 'kind': 'data_key', 'key': 'order_id'},
        ]
    }
    assert search_graph(graph, 'save_order', kind='symbol')[0]['node_id'] == 's'
    assert search_graph(graph, 'order_id', kind='key')[0]['node_id'] == 'k'


def test_reciprocal_rank_fusion_ignores_score_scales():
    fused = reciprocal_rank_fusion(
        {
            'lexical': [{'chunk_id': 'a'}, {'chunk_id': 'b'}],
            'semantic': [{'chunk_id': 'b'}, {'chunk_id': 'a'}],
        },
        k=1,
    )
    assert {item['chunk_id'] for item in fused} == {'a', 'b'}
    assert fused[0]['score'] == fused[1]['score']
    assert fused[0]['source'] == 'hybrid'


def test_hybrid_search_routes_exact_symbol_without_semantic_store():
    index = {
        'chunks': [{'id': 'x', 'path': 'src/orders.py', 'symbol': 'save_order', 'content': ''}]
    }
    graph = {
        'nodes': [
            {'id': 'node:x', 'chunk_id': 'x', 'symbol': 'save_order', 'path': 'src/orders.py'}
        ]
    }
    results = search_hybrid(index, graph, 'save_order', lexical_kind='symbol', exact=True)
    assert results[0]['source'] == 'hybrid'


def test_end_to_end_hybrid_search():
    index = {
        'chunks': [
            {
                'id': 'x',
                'path': 'src/orders.py',
                'symbol': 'save_order',
                'content': "storage['order_id'] = value",
            }
        ]
    }
    graph = {
        'nodes': [
            {
                'id': 'node:x',
                'kind': 'python_symbol',
                'chunk_id': 'x',
                'symbol': 'save_order',
                'path': 'src/orders.py',
            }
        ]
    }
    results = search_hybrid(
        index, graph, 'save_order', lexical_kind='symbol', structural_kind='symbol', exact=True
    )
    assert results[0]['chunk_id'] == 'x'
    assert results[0]['source'] == 'hybrid'


def test_hybrid_search_propagates_structural_access_evidence():
    results = hybrid_search(
        [{'chunk_id': 'reader', 'score': 1.0}],
        [{'chunk_id': 'reader', 'node_id': 'key-node', 'score': 0.8, 'access_types': ['reads']}],
        access='reads',
    )
    assert results[0]['access_types'] == ['reads']
    assert results[0]['structural_node_ids'] == ['key-node']


def test_hybrid_search_rejects_invalid_two_stage_parameters():
    import pytest

    with pytest.raises(ValueError, match='semantic_initial_k must be positive'):
        search_hybrid({}, {}, 'query', semantic_initial_k=0)
    with pytest.raises(ValueError, match='semantic_v2_weight must be non-negative'):
        search_hybrid({}, {}, 'query', semantic_v2_weight=-1)


def test_hybrid_search_accepts_two_stage_profile_without_store():
    index = {'chunks': []}
    assert search_hybrid(index, {'nodes': []}, 'query', semantic_profile='two_stage') == []


def test_hybrid_search_prioritizes_access_profile():
    results = hybrid_search(
        [{'chunk_id': 'noise', 'score': 1.0}],
        [{'chunk_id': 'reader', 'score': 0.1, 'access_types': ['reads']}],
        access='reads',
    )
    assert results[0]['chunk_id'] == 'reader'


def test_hybrid_search_merges_semantic_results():
    results = hybrid_search(
        [{'chunk_id': 'x', 'score': 0.8, 'match_kinds': ['content']}],
        [],
        [{'chunk_id': 'x', 'score': 0.7, 'source': 'semantic'}],
    )
    assert results[0]['source'] == 'hybrid'
    assert results[0]['sources'] == ['lexical', 'semantic']


def test_hybrid_search_merges_by_chunk():
    results = hybrid_search(
        [{'chunk_id': 'x', 'score': 0.8, 'match_kinds': ['content']}],
        [{'node_id': 'x', 'score': 1.0, 'match_kinds': ['symbol']}],
    )
    assert results == [
        {
            'chunk_id': 'x',
            'score': 1.0,
            'match_kinds': ['content', 'symbol'],
            'source': 'hybrid',
            'structural_node_ids': ['x'],
            'sources': ['lexical', 'structural'],
        }
    ]
