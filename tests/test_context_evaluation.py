from coderag.context_evaluation import evaluate_context_package


def test_context_evaluation_reports_coverage_and_budget():
    package = {'items': [{'chunk': {'id': 'a'}, 'content_truncated': True}], 'estimated_tokens': 4}
    metrics = evaluate_context_package(package, {'a', 'b'})
    assert metrics['coverage'] == 0.5
    assert metrics['truncated_items'] == 1
    assert metrics['estimated_tokens'] == 4
