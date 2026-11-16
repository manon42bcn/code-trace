from coderag.context_flow import _literal_path_status, context_flow


def _chunk(name, code):
    return {
        'id': name,
        'path': 'features/steps/steps.py',
        'symbol': name,
        'language': 'python',
        'strategy': 'python_ast',
        'start_line': 1,
        'content': code,
    }


def _r(line, name, scenario='scenario: main'):
    return {
        'feature_path': 'features/demo.feature',
        'scenario': scenario,
        'line_approx': line,
        'definitions': [{'repository': 'r', 'chunk_id': name}] if name else [],
    }


def test_primary_storage_route_is_not_claimed_runtime_verified():
    index = {'chunks': [_chunk('write', 'def write(context):\n    context.storage["key"] = 1\n')]}
    result = context_flow(
        {'r': index},
        [{'kind': 'context', 'key': 'key', 'relation_index': 1}],
        [_r(2, 'write'), _r(3, None)],
    )
    candidate = result['reference_producer_links'][0]['candidates'][0]
    assert candidate['route_classification'] == 'static_path_candidate'
    assert candidate['route_conditions'] == []
    assert candidate['runtime_verified'] is False


def test_behave_fallback_is_conditional():
    index = {'chunks': [_chunk('write', 'def write(context):\n    context.key = 1\n')]}
    result = context_flow(
        {'r': index},
        [{'kind': 'context', 'key': 'key', 'relation_index': 1}],
        [_r(2, 'write'), _r(3, None)],
    )
    candidate = result['reference_producer_links'][0]['candidates'][0]
    assert candidate['route_classification'] == 'conditional_path'
    assert 'storage_key_must_be_absent' in candidate['route_conditions']


def test_dotted_reference_records_unproven_traversal():
    index = {
        'chunks': [
            _chunk('write', 'def write(context):\n    context.storage["key"] = make_value()\n')
        ]
    }
    result = context_flow(
        {'r': index},
        [{'kind': 'context', 'key': 'key.id', 'relation_index': 1}],
        [_r(2, 'write'), _r(3, None)],
    )
    link = result['reference_producer_links'][0]
    assert link['nested_segments'] == ['id']
    assert link['candidates'][0]['nested_path_status'] == 'unknown_dynamic_value'
    assert link['candidates'][0]['route_classification'] == 'conditional_path'


def test_later_previous_step_flags_possible_overwrite():
    index = {
        'chunks': [
            _chunk('first', 'def first(context):\n    context.storage["key"] = 1\n'),
            _chunk('second', 'def second(context):\n    context.storage["key"] = 2\n'),
        ]
    }
    result = context_flow(
        {'r': index},
        [{'kind': 'context', 'key': 'key', 'relation_index': 2}],
        [_r(2, 'first'), _r(3, 'second'), _r(4, None)],
    )
    candidates = result['reference_producer_links'][0]['candidates']
    first = next(
        c for c in candidates if result['producers'][c['producer_id']]['symbol'] == 'first'
    )
    assert 'later_prior_step_may_overwrite' in first['route_conditions']
    assert first['route_classification'] == 'conditional_path'


def test_separate_scenarios_do_not_create_prior_step_route():
    index = {'chunks': [_chunk('first', 'def first(context):\n    context.storage["key"] = 1\n')]}
    result = context_flow(
        {'r': index},
        [{'kind': 'context', 'key': 'key', 'relation_index': 1}],
        [_r(2, 'first', 'scenario: other'), _r(3, None)],
    )
    assert (
        result['reference_producer_links'][0]['candidates'][0]['route_classification']
        == 'insufficient_evidence'
    )


def test_literal_path_can_be_proved_or_rejected_when_known():
    assert (
        _literal_path_status({'value_kind': 'literal', 'literal_value': {'id': 1}}, ['id'])
        == 'literal_path_supported'
    )
    assert (
        _literal_path_status({'value_kind': 'literal', 'literal_value': {'id': 1}}, ['missing'])
        == 'literal_path_not_found'
    )
