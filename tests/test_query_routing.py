from coderag.query_routing import classify_query, retrieval_sources


def test_query_intents_are_provider_neutral():
    assert classify_query('save_order', kind='symbol') == 'exact_symbol'
    assert classify_query('src/orders.py', kind='path') == 'exact_path'
    assert classify_query('order_id', kind='content') == 'storage_key'
    assert classify_query('where is order creation handled') == 'natural_language'


def test_source_priority_matches_intent():
    assert retrieval_sources('exact_symbol')[0] == 'lexical'
    assert retrieval_sources('natural_language')[0] == 'semantic'
    assert 'structural' in retrieval_sources('storage_key')
