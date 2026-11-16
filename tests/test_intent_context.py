from coderag.intent_context import build_context_for_query


def test_context_defaults_follow_generic_intent():
    index = {'chunks': [{'id': 'a', 'content': 'a'}]}
    context = build_context_for_query(
        index,
        {'nodes': [], 'edges': []},
        'save_order',
        [{'chunk_id': 'a', 'score': 1}],
        intent='exact_symbol',
    )
    assert context['intent'] == 'exact_symbol'
    assert context['query'] == 'save_order'
