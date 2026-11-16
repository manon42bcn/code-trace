from coderag.embedding_text import EMBEDDING_TEXT_VERSION, chunk_embedding_text


def test_chunk_embedding_text_is_deterministic_and_contextual():
    chunk = {
        'path': 'src/orders.py',
        'language': 'python',
        'symbol': 'save_order',
        'parent_symbol': 'OrderService',
        'content': 'return order_id',
    }
    expected = (
        'Repository: demo\nPath: src/orders.py\nLanguage: python\nSymbol: '
        'save_order\nParent: OrderService\nCode:\nreturn order_id'
    )
    assert chunk_embedding_text(chunk, repository='demo') == expected
    assert chunk_embedding_text(chunk, repository='demo') == chunk_embedding_text(
        chunk, repository='demo'
    )
    enriched = chunk_embedding_text(
        chunk,
        repository='demo',
        related_keys=['order_id'],
        access_types=['writes'],
        relations=['calls'],
    )
    assert 'Related keys: order_id' in enriched
    assert 'Access types: writes' in enriched
    assert 'Relations: calls' in enriched
    assert EMBEDDING_TEXT_VERSION == 'v2'
