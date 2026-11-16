from coderag.context_flow import _lifecycle_events, context_flow


def chunk(symbol, content, path='features/steps/example.py'):
    return {
        'id': symbol,
        'symbol': symbol,
        'path': path,
        'language': 'python',
        'strategy': 'python_ast',
        'start_line': 1,
        'content': content,
    }


def rel(line, definition, scenario='scenario: demo'):
    return {
        'feature_path': 'features/demo.feature',
        'scenario': scenario,
        'line_approx': line,
        'definitions': [{'repository': 'r', 'chunk_id': definition}] if definition else [],
    }


def test_future_writer_does_not_become_prior_path():
    index = {'chunks': [chunk('write', 'def write(context):\n    context.storage["k"] = 3\n')]}
    result = context_flow(
        {'r': index},
        [{'kind': 'context', 'key': 'k', 'relation_index': 0}],
        [rel(2, None), rel(3, 'write')],
    )
    candidate = result['reference_producer_links'][0]['candidates'][0]
    assert candidate['temporal_evidence'] == 'future_step_only'
    assert candidate['future_step_lines'] == [3]
    assert candidate['route_classification'] == 'insufficient_evidence'
    assert not candidate['latest_known_prior_writer']


def test_overwrite_witness_marks_older_producer_but_not_last():
    index = {
        'chunks': [
            chunk('a', 'def a(context):\n    context.storage["k"] = 1\n'),
            chunk('b', 'def b(context):\n    context.storage["k"] = 2\n'),
        ]
    }
    result = context_flow(
        {'r': index},
        [{'kind': 'context', 'key': 'k', 'relation_index': 2}],
        [rel(2, 'a'), rel(3, 'b'), rel(4, None)],
    )
    cs = result['reference_producer_links'][0]['candidates']
    by_symbol = {result['producers'][c['producer_id']]['symbol']: c for c in cs}
    assert by_symbol['a']['later_prior_writer_step_lines'] == [3]
    assert not by_symbol['a']['latest_known_prior_writer']
    assert by_symbol['b']['latest_known_prior_writer']
    assert by_symbol['b']['later_prior_writer_step_lines'] == []


def test_other_scenario_does_not_count_future_writer():
    index = {'chunks': [chunk('write', 'def write(context):\n    context.storage["k"] = 3\n')]}
    result = context_flow(
        {'r': index},
        [{'kind': 'context', 'key': 'k', 'relation_index': 0}],
        [rel(2, None), rel(3, 'write', 'scenario: other')],
    )
    assert (
        result['reference_producer_links'][0]['candidates'][0]['temporal_evidence']
        == 'not_ordered_in_scenario'
    )


def test_hook_rebind_is_not_reported_as_clearing_all_layers():
    code = (
        'def before_scenario(context, scenario):\n    context.storage = '
        'collections.ChainMap({}, context.feature_storage, '
        'context.run_storage)\n'
    )
    result = _lifecycle_events(
        {'r': {'chunks': [chunk('before_scenario', code, 'toolium/behave/environment.py')]}}
    )
    assert len(result) == 1
    assert result[0]['scope'] == 'scenario'
    assert result[0]['effect'] == 'chainmap_rebind'
    assert result[0]['runtime_verified'] is False


def test_feature_storage_reset_distinguished_from_chainmap_rebind():
    code = (
        'def before_feature(context, feature):\n    '
        'context.feature_storage = {}\n    context.storage = '
        'collections.ChainMap(context.feature_storage, '
        'context.run_storage)\n'
    )
    result = _lifecycle_events(
        {'r': {'chunks': [chunk('before_feature', code, 'toolium/behave/environment.py')]}}
    )
    assert {x['attribute']: x['effect'] for x in result} == {
        'feature_storage': 'new_empty_dict',
        'storage': 'chainmap_rebind',
    }
