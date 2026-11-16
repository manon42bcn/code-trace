from coderag.context_flow import context_flow
from coderag.execution_paths import call_graph


def ch(cid, path, symbol, code, strategy='python_ast'):
    return {
        'id': cid,
        'path': path,
        'language': 'python',
        'strategy': strategy,
        'symbol': symbol,
        'start_line': 1,
        'content': code,
    }


def relation(scenario, line, cid):
    return {
        'feature_path': 'pkg/features/sample.feature',
        'scenario': scenario,
        'line_approx': line,
        'definitions': [{'repository': 'project', 'chunk_id': cid}],
    }


def test_relative_import_links_prior_step_to_writer():
    chunks = [
        ch(
            'imports',
            'pkg/steps.py',
            None,
            'from .helpers import save_id as save',
            'surrounding_code',
        ),
        ch('step', 'pkg/steps.py', 'create', 'def create(context):\n    save(context)'),
        ch(
            'writer',
            'pkg/helpers.py',
            'save_id',
            'def save_id(context):\n    context.storage["dataset_id"] = "abc"',
        ),
        ch('reader', 'pkg/steps.py', 'consume', 'def consume(context):\n    pass'),
    ]
    indexes = {'project': {'chunks': chunks}}
    graph, _ = call_graph(indexes)
    assert ('project', 'writer') in graph[('project', 'step')]
    flow = context_flow(
        indexes,
        [{'kind': 'context', 'key': 'dataset_id', 'relation_index': 1}],
        [relation('scenario: A', 10, 'step'), relation('scenario: A', 20, 'reader')],
    )
    candidate = flow['reference_producer_links'][0]['candidates'][0]
    assert candidate['tier'] == 'preceding_direct_call_candidate'
    assert candidate['producer_step_line'] == 10
    assert candidate['temporal_evidence'] == 'prior_step_witness'
    assert [x['chunk_id'] for x in candidate['witness_path']] == ['step', 'writer']


def test_relative_import_cannot_escape_root_or_link_other_scenario():
    chunks = [
        ch('imports', 'pkg/steps.py', None, 'from ...other import save', 'surrounding_code'),
        ch('step', 'pkg/steps.py', 'create', 'def create(context):\n    save(context)'),
        ch(
            'writer',
            'other.py',
            'save',
            'def save(context):\n    context.storage["dataset_id"] = 1',
        ),
    ]
    indexes = {'project': {'chunks': chunks}}
    graph, _ = call_graph(indexes)
    assert ('project', 'writer') not in graph.get(('project', 'step'), set())
    flow = context_flow(
        indexes,
        [{'kind': 'context', 'key': 'dataset_id', 'relation_index': 1}],
        [relation('scenario: B', 10, 'step'), relation('scenario: A', 20, 'step')],
    )
    assert all(
        not c['tier'].startswith('preceding_')
        for c in flow['reference_producer_links'][0]['candidates']
    )


def test_absolute_import_and_alias_still_resolve():
    indexes = {
        'project': {
            'chunks': [
                ch(
                    'im',
                    'pkg/steps.py',
                    None,
                    'from pkg.helpers import save as persist',
                    'surrounding_code',
                ),
                ch('a', 'pkg/steps.py', 'create', 'def create(context):\n    persist(context)'),
                ch(
                    'b',
                    'pkg/helpers.py',
                    'save',
                    'def save(context):\n    context.storage["key"] = 1',
                ),
            ]
        }
    }
    graph, _ = call_graph(indexes)
    assert ('project', 'b') in graph[('project', 'a')]


def test_gherkin_argument_bound_writer_is_prior_only_in_same_scenario():
    chunks = [
        ch(
            'write',
            'pkg/steps.py',
            'store_key',
            'def store_key(context, storage_key):\n    context.storage[storage_key] = 42',
        ),
        ch('consume', 'pkg/steps.py', 'consume', 'def consume(context):\n    pass'),
    ]
    indexes = {'project': {'chunks': chunks}}

    def writer(scenario, line):
        return {
            'feature_path': 'pkg/features/sample.feature',
            'scenario': scenario,
            'line_approx': line,
            'resolved_text': 'save as "dataset_id"',
            'definitions': [
                {'repository': 'project', 'chunk_id': 'write', 'pattern': 'save as "{storage_key}"'}
            ],
        }

    def consumer(scenario, line):
        return {
            'feature_path': 'pkg/features/sample.feature',
            'scenario': scenario,
            'line_approx': line,
            'definitions': [{'repository': 'project', 'chunk_id': 'consume'}],
        }

    refs = [{'kind': 'context', 'key': 'dataset_id', 'relation_index': 1}]
    flow = context_flow(indexes, refs, [writer('scenario: A', 10), consumer('scenario: A', 20)])
    cs = flow['reference_producer_links'][0]['candidates']
    assert len(cs) == 1
    assert cs[0]['tier'] == 'preceding_scenario_step_candidate'
    assert cs[0]['producer_step_line'] == 10
    assert cs[0]['evidence'] == 'gherkin_parameter_bound_to_storage_write'
    assert cs[0]['temporal_evidence'] == 'prior_step_witness'
    for relations in (
        [writer('scenario: B', 10), consumer('scenario: A', 20)],
        [writer('scenario: A', 30), consumer('scenario: A', 20)],
    ):
        result = context_flow(indexes, refs, relations)
        assert not result['reference_producer_links'][0]['candidates']


def test_unbound_dynamic_storage_key_not_invented():
    chunks = [
        ch(
            'write',
            'pkg/steps.py',
            'store_key',
            'def store_key(context, key):\n    context.storage[key] = 42',
        )
    ]
    indexes = {'project': {'chunks': chunks}}
    rels = [
        {
            'feature_path': 'pkg/features/sample.feature',
            'scenario': 'scenario: A',
            'line_approx': 10,
            'resolved_text': 'save dataset_id',
            'definitions': [
                {'repository': 'project', 'chunk_id': 'write', 'pattern': 'save fixed'}
            ],
        },
        {
            'feature_path': 'pkg/features/sample.feature',
            'scenario': 'scenario: A',
            'line_approx': 20,
            'definitions': [],
        },
    ]
    flow = context_flow(
        indexes, [{'kind': 'context', 'key': 'dataset_id', 'relation_index': 1}], rels
    )
    assert not flow['reference_producer_links'][0]['candidates']
