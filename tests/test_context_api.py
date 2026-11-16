from coderag.context_api import build_context


def test_context_api_unifies_building_and_evaluation():
    package = build_context(
        {'chunks': [{'id': 'a', 'content': 'code'}]},
        {'nodes': [], 'edges': []},
        'save_order',
        [{'chunk_id': 'a', 'score': 1.0}],
        intent='exact_symbol',
        relevant_chunk_ids={'a'},
    )
    assert package['api_version'] == '1'
    assert package['intent'] == 'exact_symbol'
    assert package['evaluation']['coverage'] == 1.0
