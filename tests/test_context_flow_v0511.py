from coderag.context_flow import context_flow, context_inventory


def chunk(code, cid='a', path='acceptance/features/steps/custom.py', symbol='step'):
    return {
        'id': cid,
        'path': path,
        'language': 'python',
        'strategy': 'python_ast',
        'symbol': symbol,
        'start_line': 1,
        'content': code,
    }


def test_store_is_not_read():
    p, c, _ = context_inventory(
        {'chunks': [chunk('def f(context):\n    context.count = 1\n    context["name"] = "ok"')]},
        'r',
    )
    assert {x['key'] for x in p} == {'count', 'name'}
    assert c == []


def test_augmented_assignment_and_actual_read():
    p, c, _ = context_inventory(
        {'chunks': [chunk('def f(context):\n    context.count += 1\n    v = context.name')]}, 'r'
    )
    assert any(x['key'] == 'count' for x in p)
    assert any(x['key'] == 'name' and x['operation'] == 'read' for x in c)


def test_evidence_tier_and_dedup():
    idx = {'chunks': [chunk('def f(context):\n    context.token = "a"')]}
    refs = [{'kind': 'context', 'key': 'token', 'relation_index': 0}]
    rels = [
        {
            'feature_path': 'acceptance/features/login.feature',
            'definitions': [{'repository': 'r', 'chunk_id': 'a'}],
        }
    ]
    flow = context_flow({'r': idx}, refs, rels)
    assert flow['reference_producer_links'][0]['candidates'][0]['tier'] == 'matched_step_definition'
    assert flow['reference_producer_links'][0]['runtime_verified'] is False


def test_unscoped_producer_is_only_key_candidate():
    idx = {'chunks': [chunk('def f(context):\n    context.token = "a"', path='support/utils.py')]}
    flow = context_flow(
        {'r': idx},
        [{'kind': 'context', 'key': 'token', 'relation_index': 0}],
        [{'feature_path': 'acceptance/features/a.feature', 'definitions': []}],
    )
    assert flow['reference_producer_links'][0]['candidates'][0]['tier'] == 'key_only_candidate'
