from coderag.context_flow import context_flow


def chunk(cid, symbol, code):
    return {
        'id': cid,
        'path': 'acceptance/features/steps/sample.py',
        'language': 'python',
        'strategy': 'python_ast',
        'symbol': symbol,
        'start_line': 1,
        'content': code,
    }


def rel(scenario, line, definition, row=None):
    return {
        'feature_path': 'acceptance/features/test.feature',
        'scenario': scenario,
        'line_approx': line,
        'example_row': row,
        'definitions': [{'repository': 'project', 'chunk_id': definition}],
    }


def rank(chunks, relations, consumer=1):
    result = context_flow(
        {'project': {'chunks': chunks}},
        [{'kind': 'context', 'key': 'token', 'relation_index': consumer}],
        relations,
    )
    return result['reference_producer_links'][0]['candidates'][0]['tier']


def test_previous_step_ranked_above_scope():
    chunks = [
        chunk('p', 'produce', 'def produce(context):\n    context.token = 1'),
        chunk('c', 'consume', 'def consume(context):\n    pass'),
    ]
    assert (
        rank(chunks, [rel('scenario: A', 10, 'p'), rel('scenario: A', 20, 'c')])
        == 'preceding_scenario_step_candidate'
    )


def test_future_step_not_considered_previous():
    chunks = [chunk('p', 'produce', 'def produce(context):\n    context.token = 1')]
    assert (
        rank(chunks, [rel('scenario: A', 30, 'p'), rel('scenario: A', 20, 'c')])
        == 'same_feature_scope_candidate'
    )


def test_unrelated_scenario_not_considered_previous():
    chunks = [chunk('p', 'produce', 'def produce(context):\n    context.token = 1')]
    assert (
        rank(chunks, [rel('scenario: B', 10, 'p'), rel('scenario: A', 20, 'c')])
        == 'same_feature_scope_candidate'
    )


def test_other_examples_row_not_considered_previous():
    chunks = [chunk('p', 'produce', 'def produce(context):\n    context.token = 1')]
    assert (
        rank(
            chunks,
            [
                rel('scenario_outline: A', 10, 'p', row=1),
                rel('scenario_outline: A', 20, 'c', row=2),
            ],
        )
        == 'same_feature_scope_candidate'
    )


def test_background_can_precede_scenario():
    chunks = [chunk('p', 'produce', 'def produce(context):\n    context.token = 1')]
    assert (
        rank(chunks, [rel('background: common', 3, 'p'), rel('scenario: A', 20, 'c')])
        == 'preceding_scenario_step_candidate'
    )


def test_direct_call_one_hop():
    chunks = [
        chunk('p', 'produce', 'def produce(context):\n    context.token = 1'),
        chunk('w', 'wrapper', 'def wrapper(context):\n    produce(context)'),
    ]
    assert (
        rank(chunks, [rel('scenario: A', 10, 'w'), rel('scenario: A', 20, 'c')])
        == 'preceding_direct_call_candidate'
    )
