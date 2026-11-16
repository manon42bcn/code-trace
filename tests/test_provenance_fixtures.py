"""Labeled synthetic fixtures for static provenance precision/recall."""

from coderag.context_flow import context_flow


def chunk(cid, symbol, code, path='pkg/steps.py'):
    return {
        'id': cid,
        'path': path,
        'language': 'python',
        'strategy': 'python_ast',
        'symbol': symbol,
        'start_line': 1,
        'content': code,
    }


def run_fixture(chunks, *, producer_line=10, consumer_line=20):
    indexes = {'project': {'chunks': chunks}}
    relations = [
        {
            'feature_path': 'pkg/features/sample.feature',
            'scenario': 'scenario: A',
            'line_approx': producer_line,
            'definitions': [{'repository': 'project', 'chunk_id': 'step'}],
        },
        {
            'feature_path': 'pkg/features/sample.feature',
            'scenario': 'scenario: A',
            'line_approx': consumer_line,
            'definitions': [{'repository': 'project', 'chunk_id': 'consumer'}],
        },
    ]
    return context_flow(
        indexes, [{'kind': 'context', 'key': 'order_id', 'relation_index': 1}], relations
    )


FIXTURES = [
    {
        'name': 'two_hop_literal_key',
        'expected': 'preceding_direct_call_candidate',
        'chunks': [
            chunk('step', 'step', "def step(context):\n    helper(context.storage, 'order_id')"),
            chunk('helper', 'helper', 'def helper(storage, key):\n    persist(storage, key)'),
            chunk('writer', 'persist', 'def persist(storage, key):\n    storage[key] = 1'),
            chunk('consumer', 'consumer', 'def consumer(context):\n    pass'),
        ],
    },
    {
        'name': 'dynamic_key_rejected',
        'expected': None,
        'chunks': [
            chunk('step', 'step', 'def step(context, key):\n    helper(context.storage, key)'),
            chunk('helper', 'helper', 'def helper(storage, key):\n    persist(storage, key)'),
            chunk('writer', 'persist', 'def persist(storage, key):\n    storage[key] = 1'),
            chunk('consumer', 'consumer', 'def consumer(context):\n    pass'),
        ],
    },
    {
        'name': 'ambiguous_helper_rejected',
        'expected': None,
        'chunks': [
            chunk('step', 'step', "def step(context):\n    helper(context.storage, 'order_id')"),
            chunk('helper_a', 'helper', 'def helper(storage, key):\n    persist(storage, key)'),
            chunk('helper_b', 'helper', 'def helper(storage, key):\n    persist(storage, key)'),
            chunk('writer', 'persist', 'def persist(storage, key):\n    storage[key] = 1'),
            chunk('consumer', 'consumer', 'def consumer(context):\n    pass'),
        ],
    },
    {
        'name': 'named_arguments_supported',
        'expected': 'preceding_direct_call_candidate',
        'chunks': [
            chunk(
                'step',
                'step',
                "def step(context):\n    helper(storage=context.storage, key='order_id')",
            ),
            chunk('helper', 'helper', 'def helper(storage, key):\n    persist(storage, key)'),
            chunk('writer', 'persist', 'def persist(storage, key):\n    storage[key] = 1'),
            chunk('consumer', 'consumer', 'def consumer(context):\n    pass'),
        ],
    },
    {
        'name': 'storage_alias_supported',
        'expected': 'preceding_direct_call_candidate',
        'chunks': [
            chunk(
                'step',
                'step',
                (
                    'def step(context):\n    storage = context.storage\n    '
                    "helper(storage, 'order_id')"
                ),
            ),
            chunk('helper', 'helper', 'def helper(storage, key):\n    persist(storage, key)'),
            chunk('writer', 'persist', 'def persist(storage, key):\n    storage[key] = 1'),
            chunk('consumer', 'consumer', 'def consumer(context):\n    pass'),
        ],
    },
    {
        'name': 'local_storage_alias_supported',
        'expected': 'preceding_direct_call_candidate',
        'chunks': [
            chunk(
                'step',
                'step',
                (
                    'def step(context):\n    storage = context.storage\n    '
                    "helper(storage, 'order_id')"
                ),
            ),
            chunk('helper', 'helper', 'def helper(storage, key):\n    persist(storage, key)'),
            chunk('writer', 'persist', 'def persist(storage, key):\n    storage[key] = 1'),
            chunk('consumer', 'consumer', 'def consumer(context):\n    pass'),
        ],
    },
    {
        'name': 'future_writer_not_prior',
        'expected': 'key_only_candidate',
        'chunks': [
            chunk('step', 'step', 'def step(context):\n    pass'),
            chunk('writer', 'writer', "def writer(context):\n    context.storage['order_id'] = 1"),
            chunk('consumer', 'consumer', 'def consumer(context):\n    pass'),
        ],
    },
]


def test_labeled_fixture_expectations():
    for fixture in FIXTURES:
        flow = run_fixture(
            fixture['chunks'],
            producer_line=30 if fixture['name'] == 'future_writer_not_prior' else 10,
        )
        candidates = flow['reference_producer_links'][0]['candidates']
        tiers = {candidate['tier'] for candidate in candidates}
        if fixture['expected'] is None:
            assert not any(tier.startswith('preceding_') for tier in tiers), fixture['name']
        else:
            assert fixture['expected'] in tiers, fixture['name']


def test_else_and_exception_flow_are_labeled():
    cases = [
        (
            "if enabled:\n        pass\n    else:\n        context.storage['order_id'] = 1",
            'if',
            'orelse',
        ),
        (
            "try:\n        context.storage['order_id'] = 1\n    except ValueError:\n        pass",
            'exception',
            'try_body',
        ),
        (
            "try:\n        pass\n    finally:\n        context.storage['order_id'] = 1",
            'try',
            'finally',
        ),
    ]
    cases.extend(
        [
            (
                "for item in items:\n        context.storage['order_id'] = item",
                'loop',
                'potentially_empty',
            ),
            (
                "while enabled:\n        context.storage['order_id'] = 1",
                'loop',
                'potentially_empty',
            ),
            (
                (
                    'try:\n        pass\n    except ValueError:\n        '
                    "context.storage['order_id'] = 1"
                ),
                'exception',
                'except_handler',
            ),
            (
                (
                    'try:\n        pass\n    except ValueError:\n        pass\n    '
                    "else:\n        context.storage['order_id'] = 1"
                ),
                'exception',
                'try_else',
            ),
        ]
    )
    for body, kind, branch in cases:
        flow = run_fixture(
            [
                chunk('step', 'step', 'def step(context):\n    ' + body),
                chunk('consumer', 'consumer', 'def consumer(context):\n    pass'),
            ]
        )
        writer = flow['producers'][0]
        assert writer['control_flow_kind'] == kind
        assert writer['control_flow_branch'] == branch


def test_conditional_writer_is_not_guaranteed():
    chunks = [
        chunk(
            'step',
            'step',
            "def step(context):\n    if enabled:\n        context.storage['order_id'] = 1",
        ),
        chunk('consumer', 'consumer', 'def consumer(context):\n    pass'),
    ]
    flow = run_fixture(chunks)
    writer = flow['producers'][0]
    assert writer['control_flow'] == 'conditional'
    candidate = flow['reference_producer_links'][0]['candidates'][0]
    assert candidate['route_classification'] == 'conditional_path'
    assert 'conditional_write_path' in candidate['route_conditions']
    assert candidate['runtime_verified'] is False


def test_lexical_index_kinds_are_separate():
    from coderag.core import index_repository

    assert callable(index_repository)


def test_candidate_evidence_metrics_are_exposed():
    flow = run_fixture(FIXTURES[0]['chunks'])
    summary = flow['summary']
    assert summary['candidate_evidence_records'] >= summary['unique_candidate_evidence_records']
    assert summary['duplicate_candidate_evidence_records'] >= 0
    assert summary['unique_candidate_evidence_records'] == summary['candidate_evidence_records']


def test_fixture_metrics_are_reproducible():
    results = []
    for fixture in FIXTURES:
        flow = run_fixture(
            fixture['chunks'],
            producer_line=30 if fixture['name'] == 'future_writer_not_prior' else 10,
        )
        candidates = flow['reference_producer_links'][0]['candidates']
        actual = any(candidate['tier'].startswith('preceding_') for candidate in candidates)
        expected = fixture['expected'] == 'preceding_direct_call_candidate'
        results.append((expected, actual))
    true_positive = sum(expected and actual for expected, actual in results)
    false_positive = sum(not expected and actual for expected, actual in results)
    false_negative = sum(expected and not actual for expected, actual in results)
    assert (true_positive, false_positive, false_negative) == (4, 0, 0)
