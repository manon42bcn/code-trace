from coderag.two_stage_retrieval import two_stage_retrieve


def test_two_stage_keeps_v1_candidates_and_expands_with_v2():
    result = two_stage_retrieve(
        [{'chunk_id': 'a', 'score': 0.9}, {'chunk_id': 'b', 'score': 0.8}],
        [{'chunk_id': 'c', 'score': 0.95}, {'chunk_id': 'a', 'score': 0.7}],
        initial_k=1,
        limit=2,
        v2_weight=0.1,
    )
    assert [item['chunk_id'] for item in result] == ['a', 'c']
    assert result[0]['source'] == 'semantic-v1-v2'
    assert result[1]['source'] == 'semantic-v2-expansion'
