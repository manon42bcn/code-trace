from coderag.embedding_fusion import fuse_embedding_results


def test_embedding_fusion_uses_configurable_weights():
    results = fuse_embedding_results(
        {
            'v1': [{'chunk_id': 'a', 'score': 0.8}, {'chunk_id': 'b', 'score': 0.7}],
            'v2': [{'chunk_id': 'b', 'score': 0.9}],
        },
        weights={'v1': 1.0, 'v2': 0.1},
    )
    assert results[0]['chunk_id'] == 'a'
    assert results[1]['sources'] == ['v1', 'v2']
