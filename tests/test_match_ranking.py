"""Identifier signals precede source caps while preserving explicit access and match semantics."""

from coderag.hybrid_search import hybrid_search
from coderag.lexical_search import search_index
from coderag.match_ranking import describe_match
from coderag.search import search_hybrid
from coderag.structural_search import search_graph


def test_exact_definition_precedes_partial_symbol_before_top_k():
    index = {
        'chunks': [
            {
                'id': 'a',
                'path': 'a.py',
                'language': 'python',
                'symbol': 'save_order_retry',
                'content': 'def save_order_retry(): pass',
            },
            {
                'id': 'z',
                'path': 'z.py',
                'language': 'python',
                'symbol': 'save_order',
                'content': 'def save_order(): pass',
            },
        ]
    }
    result = search_index(index, 'save_order', limit=1)[0]
    assert result['chunk_id'] == 'z'
    assert result['ranking']['role'] == 'definition'
    assert result['score'] == 1.0
    assert len(search_index(index, 'save_order', kind='symbol', exact=True)) == 1


def test_identifier_boundary_reference_beats_partial_symbol():
    index = {
        'chunks': [
            {'id': 'a', 'path': 'a.py', 'symbol': 'store_order_id_backup', 'content': 'pass'},
            {'id': 'z', 'path': 'z.py', 'symbol': 'send', 'content': 'return context.order_id'},
        ]
    }
    result = search_index(index, 'order_id', limit=1)[0]
    assert result['chunk_id'] == 'z'
    assert result['ranking']['match'] == 'identifier_token'
    assert result['score'] == 0.8


def test_configuration_identity_declaration_beats_prose_and_partial_literals():
    index = {
        'chunks': [
            {
                'id': 'a',
                'path': 'a.yaml',
                'language': 'yaml',
                'data_path': '$/description',
                'content': 'description: calls save_order with retries',
            },
            {
                'id': 'b',
                'path': 'b.json',
                'language': 'json',
                'data_path': '$/tools/0',
                'content': '{"name":"save_order_retry"}',
            },
            {
                'id': 'z',
                'path': 'z.yaml',
                'language': 'yaml',
                'data_path': '$/tools/0',
                'content': '- tool_name: save_order\n  description: Process an order',
            },
        ]
    }
    result = search_index(index, 'save_order', limit=1)[0]
    assert result['chunk_id'] == 'z'
    assert result['ranking']['role'] == 'declaration'
    assert result['ranking']['match'] == 'exact_identity_value'
    assert (
        describe_match(
            {'language': 'json', 'data_path': '$/tools/0', 'content': '{"name":"save_order"}'},
            'save_order',
        )['role']
        == 'declaration'
    )


def test_key_declarations_are_distinct_from_access_references():
    key = {'language': 'json', 'data_path': '$/properties/order_id', 'content': '{"type":"string"}'}
    assert describe_match(key, 'order_id')['role'] == 'declaration'
    reference = describe_match({'kind': 'data_key', 'key': 'context.order_id'}, 'order_id')
    assert reference['role'] == 'access_reference'
    assert reference['match'] == 'identifier_token'
    raw = describe_match({'language': 'yaml', 'content': 'name: save_order'}, 'save_order')
    assert raw['role'] == 'reference'


def test_dotted_method_and_semantic_only_results_are_described_honestly():
    definition = {
        'language': 'python',
        'symbol': 'Client.save_order',
        'content': 'async def save_order(self): pass',
    }
    assert describe_match(definition, 'Client.save_order')['role'] == 'definition'
    assert describe_match(definition, 'save_order')['role'] == 'definition'
    semantic = describe_match({'content': 'customer balance'}, 'order_id')
    assert semantic['match'] == 'no_literal_match'
    assert semantic['role'] == 'unknown'
    assert describe_match({'content': 'find an order'}, 'find an order')['match'] == 'legacy'


def test_structural_exact_symbol_precedes_partial_node_before_top_k():
    graph = {
        'nodes': [
            {
                'id': 'a',
                'kind': 'python_symbol',
                'symbol': 'save_order_retry',
                'chunk_id': 'partial',
            },
            {'id': 'z', 'kind': 'python_symbol', 'symbol': 'save_order', 'chunk_id': 'exact'},
        ]
    }
    result = search_graph(graph, 'save_order', limit=1)[0]
    assert result['chunk_id'] == 'exact'
    assert result['ranking']['role'] == 'definition'


def test_explicit_write_profile_still_precedes_definition_signal():
    definition = {'language': 'python', 'symbol': 'order_id', 'content': 'def order_id(): pass'}
    reference = {'content': 'storage["order_id"] = value'}
    results = hybrid_search(
        [
            {
                'chunk_id': 'definition',
                'score': 1.0,
                'ranking': describe_match(definition, 'order_id'),
            }
        ],
        [
            {
                'chunk_id': 'writer',
                'score': 0.8,
                'access_types': ['writes'],
                'ranking': describe_match(reference, 'order_id'),
            }
        ],
        access='writes',
    )
    assert results[0]['chunk_id'] == 'writer'
    assert results[1]['ranking']['role'] == 'definition'


def test_fusion_preserves_strongest_signal_and_access_evidence():
    item = {'symbol': 'save_order', 'language': 'python', 'content': 'def save_order(): pass'}
    result = hybrid_search(
        [{'chunk_id': 'x', 'score': 1.0, 'ranking': describe_match(item, 'save_order')}],
        [{'chunk_id': 'x', 'score': 0.8, 'access_types': ['reads']}],
    )[0]
    assert result['ranking']['role'] == 'definition'
    assert result['access_types'] == ['reads']
    assert result['source'] == 'hybrid'
    assert result['score'] == 1.0


def test_canonical_metadata_and_readable_ties_precede_chunk_hashes():
    index = {
        'chunks': [
            {'id': 'a-hash', 'path': 'z.py', 'content': 'return order_id', 'start_line': 2},
            {'id': 'z-hash', 'path': 'a.py', 'content': 'return order_id', 'start_line': 10},
            {'id': 'b-hash', 'path': 'a.py', 'content': 'return order_id', 'start_line': 20},
        ]
    }
    results = search_hybrid(index, {}, 'order_id')
    assert [r['chunk_id'] for r in results] == ['z-hash', 'b-hash', 'a-hash']
    assert all(r['ranking']['role'] == 'reference' for r in results)


def test_description_examples_do_not_become_identity_declarations():
    item = {
        'language': 'yaml',
        'data_path': '$/description',
        'content': 'description: |\n  Example:\n    tool_name: save_order',
    }
    assert describe_match(item, 'save_order')['role'] == 'reference'
    scalar = {'language': 'json', 'data_path': '$/name', 'content': '"name": "save_order"'}
    assert describe_match(scalar, 'save_order')['role'] == 'declaration'
