from coderag.fusion_evaluation import evaluate_fusion_weights


def test_evaluate_fusion_weight_configurations():
    queries = [{'term': 'order', 'relevant_chunk_ids': {'a'}}]
    result_sets = {
        'order': {'v1': [{'chunk_id': 'a', 'score': 0.8}], 'v2': [{'chunk_id': 'b', 'score': 0.9}]}
    }
    report = evaluate_fusion_weights(
        queries, result_sets, {'v1_only': {'v1': 1.0, 'v2': 0.0}}, k_values=(1,)
    )
    assert report['v1_only']['metrics']['mrr'] == 1.0
    assert report['v1_only']['weights']['v2'] == 0.0
