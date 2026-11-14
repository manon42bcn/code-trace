from coderag.context_flow import context_flow
from coderag.hook_scope import environment_scope


def chunk(path, symbol, source):
    return {
        'id': f'{path}:{symbol}',
        'path': path,
        'language': 'python',
        'strategy': 'python_ast' if symbol else 'surrounding_code',
        'symbol': symbol,
        'content': source,
        'start_line': 1,
    }


def test_hook_output_keeps_only_relevant_lifecycle_paths():
    path = 'features/environment.py'
    idx = {
        'app': {
            'chunks': [
                chunk(
                    path,
                    'before_scenario',
                    (
                        'def before_scenario(context, scenario):\n    init(context)\n    '
                        'unrelated(context)'
                    ),
                ),
                chunk(
                    path,
                    'init',
                    (
                        'def init(context):\n    context.storage = ChainMap({}, '
                        'context.feature_storage)'
                    ),
                ),
                chunk(path, 'unrelated', 'def unrelated(context):\n    pass'),
            ]
        }
    }
    lifecycle = [
        {
            'repository': 'app',
            'path': path,
            'hook': 'init',
            'attribute': 'storage',
            'effect': 'chainmap_rebind',
        }
    ]
    r = environment_scope(idx, 'features/s.feature', 'app', lifecycle)
    assert len(r['hooks']) == 1
    assert len(r['lifecycle_events']) == 1
    assert r['hooks'][0]['chain'][-1]['hook'] == 'init'
    assert r['trace_stats']['suppressed_non_storage_paths'] >= 1


def test_context_flow_without_environment_keeps_unknown_layer():
    source = 'def write(context):\n    context.storage["value"] = 1'
    idx = {'app': {'chunks': [chunk('steps/impl.py', 'write', source)]}}
    refs = [{'kind': 'context', 'key': 'value', 'relation_index': 0}]
    rels = [
        {
            'source_repository': 'app',
            'feature_path': 'features/a.feature',
            'scenario': 'scenario: x',
            'line_approx': 3,
            'definitions': [],
        }
    ]
    result = context_flow(idx, refs, rels)
    link = result['reference_producer_links'][0]
    assert link['effective_storage_scope']['scenario_layer_reachable'] is False
    assert link['effective_storage_scope']['execution_guaranteed'] is False
    assert link['candidates'][0]['effective_layer_candidate'] == 'unknown_storage_view'
    assert link['candidates'][0]['effective_value_confirmed'] is False
