from coderag.embedding_enrichment import enrich_chunks_from_graph


def test_enrichment_keeps_access_per_chunk():
    index = {'chunks': [{'id': 'writer'}, {'id': 'reader'}]}
    graph = {
        'nodes': [
            {'id': 'w', 'chunk_id': 'writer'},
            {'id': 'r', 'chunk_id': 'reader'},
            {'id': 'k', 'kind': 'data_key', 'key': 'order_id'},
        ],
        'edges': [
            {'source': 'w', 'target': 'k', 'type': 'writes'},
            {'source': 'r', 'target': 'k', 'type': 'reads'},
        ],
    }
    enriched = enrich_chunks_from_graph(index, graph)
    by_id = {chunk['id']: chunk for chunk in enriched['chunks']}
    assert by_id['writer']['access_types'] == ['writes']
    assert by_id['reader']['access_types'] == ['reads']
    assert by_id['writer']['related_keys'] == ['order_id']
