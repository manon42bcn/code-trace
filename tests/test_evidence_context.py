from coderag.evidence_context import build_evidence_package, build_multi_chunk_context


def test_evidence_package_is_bounded_and_explicitly_uncertain():
    index = {
        'chunks': [
            {
                'id': 'c',
                'path': 'a.py',
                'language': 'python',
                'symbol': 'save',
                'start_line': 1,
                'content': 'x',
            }
        ]
    }
    graph = {'nodes': [{'id': 'n', 'kind': 'chunk', 'chunk_id': 'c'}], 'edges': []}
    package = build_evidence_package(index, graph, 'c')
    assert package['chunk']['path'] == 'a.py'
    assert package['evidence_status'] == 'static_candidate'
    assert package['certainty'] == 'static_candidate'
    assert 'runtime_observed' in package['certainty_taxonomy']
    assert package['runtime_verified'] is False
    assert package['citation'] == {
        'chunk_id': 'c',
        'path': 'a.py',
        'symbol': 'save',
        'start_line': 1,
        'end_line': None,
        'evidence_type': 'chunk',
    }


def test_multi_chunk_context_deduplicates_and_preserves_retrieval_metadata():
    index = {
        'chunks': [
            {'id': 'a', 'path': 'a.py', 'content': 'aaa'},
            {'id': 'b', 'path': 'b.py', 'content': 'bbb'},
        ]
    }
    results = [
        {'chunk_id': 'a', 'score': 1.0, 'source': 'lexical'},
        {'chunk_id': 'a', 'score': 0.9, 'source': 'semantic'},
        {'chunk_id': 'b', 'score': 0.8, 'source': 'structural'},
    ]
    context = build_multi_chunk_context(index, {'nodes': [], 'edges': []}, results, max_chunks=2)
    assert [item['chunk']['id'] for item in context['items']] == ['a', 'b']
    assert context['items'][0]['retrieval']['source'] == 'lexical'
    assert context['selected_chunks'] == 2
    limited = build_multi_chunk_context(
        index, {'nodes': [], 'edges': []}, results, max_tokens=0, max_relations=0
    )
    assert limited['selected_chunks'] == 0
    assert limited['max_tokens'] == 0


def test_multi_chunk_context_can_expand_one_structural_hop():
    index = {'chunks': [{'id': 'a', 'content': 'a'}, {'id': 'b', 'content': 'b'}]}
    graph = {
        'nodes': [{'id': 'na', 'chunk_id': 'a'}, {'id': 'nb', 'chunk_id': 'b'}],
        'edges': [{'source': 'na', 'target': 'nb', 'type': 'calls'}],
    }
    context = build_multi_chunk_context(
        index, graph, [{'chunk_id': 'a', 'score': 1}], expansion_depth=1
    )
    assert [item['chunk']['id'] for item in context['items']] == ['a', 'b']
    assert context['items'][1]['retrieval']['source'] == 'structural-expansion'
    two_hop = build_multi_chunk_context(
        index, graph, [{'chunk_id': 'a', 'score': 1}], expansion_depth=2
    )
    assert two_hop['selected_chunks'] == 2


def test_selection_accounts_for_duplicates_budget_exclusions_and_truncation():
    index = {
        'chunks': [
            {'id': 'a', 'content': 'abcdefgh'},
            {'id': 'b', 'content': 'bb'},
            {'id': 'c', 'content': 'cc'},
        ]
    }
    results = [{'chunk_id': c} for c in ('a', 'a', 'b', 'c')]
    char_limited = build_multi_chunk_context(index, {}, results, max_chars=3)
    stats = char_limited['selection']
    assert stats['retrieved_results'] == 4
    assert stats['candidate_chunks'] == 3
    assert stats['duplicate_results'] == 1
    assert stats['selected_chunks'] == 1
    assert stats['truncated_chunks'] == 1
    assert stats['excluded_by_budget'] == {'max_chars': 2, 'max_chunks': 0, 'max_tokens': 0}
    assert char_limited['items'][0]['original_content_chars'] == 8
    chunk_limited = build_multi_chunk_context(index, {}, results, max_chunks=1)
    assert chunk_limited['selection']['excluded_by_budget']['max_chunks'] == 2
    token_limited = build_multi_chunk_context(index, {}, results, max_tokens=1)
    stats = token_limited['selection']
    assert stats['excluded_by_budget']['max_tokens'] == 2
    assert stats['selected_chunks'] == 1
    assert token_limited['items'][0]['citation']['chunk_id'] == 'b'
    for context in (char_limited, chunk_limited, token_limited):
        stats = context['selection']
        assert stats['candidate_chunks'] == stats['selected_chunks'] + stats['excluded_chunks']
        assert stats['excluded_chunks'] == sum(stats['excluded_by_budget'].values())


def test_expansion_count_is_separate_from_retrieval_count():
    index = {'chunks': [{'id': 'a', 'content': 'a'}, {'id': 'b', 'content': 'b'}]}
    graph = {
        'nodes': [{'id': 'na', 'chunk_id': 'a'}, {'id': 'nb', 'chunk_id': 'b'}],
        'edges': [{'source': 'na', 'target': 'nb', 'type': 'calls'}],
    }
    context = build_multi_chunk_context(index, graph, [{'chunk_id': 'a'}], expansion_depth=1)
    assert context['selection']['retrieved_results'] == 1
    assert context['selection']['expanded_unique_chunks'] == 1
    assert context['selection']['selected_chunks'] == 2
