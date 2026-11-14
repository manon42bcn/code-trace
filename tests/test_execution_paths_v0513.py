from coderag.context_flow import context_flow
from coderag.execution_paths import call_graph, reachable


def chunk(cid, symbol, code, path='project/steps/steps.py', strategy='python_ast'):
    return {
        'id': cid,
        'path': path,
        'language': 'python',
        'strategy': strategy,
        'symbol': symbol,
        'start_line': 1,
        'content': code,
    }


def test_propagated_storage_and_key_parameters():
    from coderag.context_flow import _propagated_parameter_writers

    indexes = {
        'project': {
            'chunks': [
                chunk(
                    'caller',
                    'save_step',
                    'def save_step(context):\n    helper(context.storage, "order_id")',
                ),
                chunk('helper', 'helper', 'def helper(storage, key):\n    storage[key] = 1'),
            ]
        }
    }
    writers = _propagated_parameter_writers(indexes)
    assert [(w['namespace'], w['key']) for w in writers] == [('toolium.storage', 'order_id')]


def test_propagated_dynamic_key_is_not_invented():
    from coderag.context_flow import _propagated_parameter_writers

    indexes = {
        'project': {
            'chunks': [
                chunk(
                    'caller',
                    'save_step',
                    'def save_step(context, key):\n    helper(context.storage, key)',
                ),
                chunk('helper', 'helper', 'def helper(storage, key):\n    storage[key] = 1'),
            ]
        }
    }
    assert _propagated_parameter_writers(indexes) == []


def test_propagated_writer_gets_step_evidence():
    indexes = {
        'project': {
            'chunks': [
                chunk(
                    'step',
                    'save_step',
                    'def save_step(context):\n    helper(context.storage, "order_id")',
                ),
                chunk('helper', 'helper', 'def helper(storage, key):\n    storage[key] = 1'),
                chunk('reader', 'read', 'def read(context):\n    pass'),
            ]
        }
    }
    rels = [
        {
            'feature_path': 'features/example.feature',
            'scenario': 'scenario: same',
            'line_approx': 2,
            'definitions': [{'repository': 'project', 'chunk_id': 'step'}],
        },
        {
            'feature_path': 'features/example.feature',
            'scenario': 'scenario: same',
            'line_approx': 3,
            'definitions': [{'repository': 'project', 'chunk_id': 'reader'}],
        },
    ]
    flow = context_flow(
        indexes, [{'kind': 'context', 'key': 'order_id', 'relation_index': 1}], rels
    )
    candidate = flow['reference_producer_links'][0]['candidates'][0]
    assert candidate['tier'] == 'preceding_direct_call_candidate'
    assert [p['chunk_id'] for p in candidate['witness_path']] == ['step', 'helper']
    assert candidate['call_depth'] == 1


def test_two_hop_propagated_writer():
    from coderag.context_flow import _propagated_parameter_writers

    indexes = {
        'project': {
            'chunks': [
                chunk(
                    'step',
                    'save_step',
                    'def save_step(context):\n    helper(context.storage, "order_id")',
                ),
                chunk('helper', 'helper', 'def helper(storage, key):\n    persist(storage, key)'),
                chunk('writer', 'persist', 'def persist(storage, key):\n    storage[key] = 1'),
            ]
        }
    }
    writers = _propagated_parameter_writers(indexes)
    assert [(w['chunk_id'], w['key']) for w in writers] == [('writer', 'order_id')]
    assert writers[0]['parameter_binding']['call_depth'] == 2


def test_imported_helper_path():
    indexes = {
        'project': {
            'chunks': [
                chunk(
                    'imports',
                    None,
                    'from project.helpers import save_value',
                    strategy='surrounding_code',
                ),
                chunk('step', 'setup', 'def setup(context):\n    save_value(context)'),
                chunk(
                    'writer',
                    'save_value',
                    'def save_value(context):\n    context.token = 1',
                    'project/helpers.py',
                ),
            ]
        }
    }
    graph, _ = call_graph(indexes)
    assert [('project', 'step'), ('project', 'writer')] in [
        list(p) for p in reachable(graph, ('project', 'step'))
    ]
    rels = [
        {
            'feature_path': 'features/example.feature',
            'scenario': 'scenario: same',
            'line_approx': 2,
            'definitions': [{'repository': 'project', 'chunk_id': 'step'}],
        },
        {
            'feature_path': 'features/example.feature',
            'scenario': 'scenario: same',
            'line_approx': 3,
            'definitions': [],
        },
    ]
    flow = context_flow(indexes, [{'kind': 'context', 'key': 'token', 'relation_index': 1}], rels)
    candidate = flow['reference_producer_links'][0]['candidates'][0]
    assert candidate['tier'] == 'preceding_direct_call_candidate'
    assert [p['chunk_id'] for p in candidate['witness_path']] == ['step', 'writer']
    assert candidate['runtime_verified'] is False


def test_unresolved_definition_diagnostic():
    flow = context_flow(
        {'project': {'chunks': []}},
        [{'kind': 'context', 'key': 'not_here', 'relation_index': 1}],
        [
            {
                'feature_path': 'features/a.feature',
                'scenario': 'scenario: S',
                'line_approx': 3,
                'definitions': [],
            },
            {
                'feature_path': 'features/a.feature',
                'scenario': 'scenario: S',
                'line_approx': 5,
                'definitions': [],
            },
        ],
    )
    assert (
        'prior_steps_without_matched_definition'
        in flow['reference_producer_links'][0]['diagnostics']
    )
    assert 'no_static_writer_for_key' in flow['reference_producer_links'][0]['diagnostics']


def test_cross_repo_calls_not_invented_without_binding():
    indexes = {
        'consumer': {
            'chunks': [chunk('step', 'setup', 'def setup(context):\n    save_value(context)')]
        },
        'external': {
            'chunks': [
                chunk(
                    'writer',
                    'save_value',
                    'def save_value(context):\n    context.token=1',
                    'project/helpers.py',
                )
            ]
        },
    }
    graph, _ = call_graph(indexes)
    assert ('external', 'writer') not in graph.get(('consumer', 'step'), set())


def test_cycles_bounded():
    graph = {('r', 'a'): {('r', 'b')}, ('r', 'b'): {('r', 'a')}}
    assert list(reachable(graph, ('r', 'a'))) == [(('r', 'a'),), (('r', 'a'), ('r', 'b'))]


def test_explicit_cross_repo_import_is_traceable():
    imports = chunk(
        'imports', None, 'from project.helpers import save_value', strategy='surrounding_code'
    )
    indexes = {
        'consumer': {
            'chunks': [
                imports,
                chunk('step', 'setup', 'def setup(context):\n    save_value(context)'),
            ]
        },
        'external': {
            'chunks': [
                chunk(
                    'writer',
                    'save_value',
                    'def save_value(context):\n    context.token=1',
                    'project/helpers.py',
                )
            ]
        },
    }
    graph, _ = call_graph(indexes)
    assert ('external', 'writer') in graph[('consumer', 'step')]
