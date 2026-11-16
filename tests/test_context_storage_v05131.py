from coderag.context_flow import context_flow, context_inventory


def chunk(source):
    return {
        'id': 'c',
        'path': 'steps/a.py',
        'symbol': 'f',
        'language': 'python',
        'strategy': 'python_ast',
        'start_line': 1,
        'content': source,
    }


def test_two_namespaces_are_separate():
    p, c, _ = context_inventory(
        {
            'chunks': [
                chunk(
                    "def f(context):\n    context.token = 'behave'\n    "
                    "context.storage['token'] = 'toolium'\n    val = "
                    "context.storage['token']\n"
                )
            ]
        },
        'r',
    )
    assert {(x['namespace'], x['key']) for x in p} == {
        ('behave.context', 'token'),
        ('toolium.storage', 'token'),
    }
    assert ('toolium.storage', 'token') in {(x['namespace'], x['key']) for x in c}
    assert not any(x['namespace'] == 'behave.context' and x['key'] == 'token' for x in c)


def test_storage_priority_fallback_and_dotted_lookup():
    idx = {
        'chunks': [
            chunk(
                "def f(context):\n    context.token = 'fallback'\n    "
                "context.storage['token'] = {'nested': 1}\n"
            )
        ]
    }
    links = context_flow({'r': idx}, [{'kind': 'context', 'key': 'token.nested'}], [])[
        'reference_producer_links'
    ]
    found = links[0]['candidates']
    assert {c['namespace'] for c in found} == {'behave.context', 'toolium.storage'}
    assert links[0]['lookup_key'] == 'token'
    assert next(c for c in found if c['namespace'] == 'behave.context')['conditional_fallback']
    assert not next(c for c in found if c['namespace'] == 'toolium.storage')['conditional_fallback']


def test_helpers_and_chainmap_layers():
    idx = {
        'chunks': [
            chunk(
                "def f(context):\n    context.store_key_in_storage('token', 1)\n   "
                " context.store_key_in_storage('[FEATURE:month]', 12)\n    "
                "dataset.store_key_in_storage(context, '[RUN:year]', 2026)\n"
            )
        ]
    }
    p, _, _ = context_inventory(idx, 'r')
    assert {(x['namespace'], x['key']) for x in p if x.get('write_via')} == {
        ('toolium.storage', 'token'),
        ('toolium.feature_storage', 'month'),
        ('toolium.run_storage', 'year'),
    }


def test_context_storage_assignment_is_not_storage_key():
    p, _, _ = context_inventory(
        {
            'chunks': [
                chunk("""def f(context):
    context.storage = {}
""")
            ]
        },
        'r',
    )
    assert len(p) == 1
    assert p[0]['namespace'] == 'behave.context'
    assert p[0]['key'] == 'storage'
    assert not any(x['namespace'] == 'toolium.storage' for x in p)


def test_storage_priority_preserved():
    idx = {
        'chunks': [
            chunk(
                "def f(context):\n    context.token = 'fallback'\n    "
                "context.storage['token'] = 'primary'\n"
            )
        ]
    }
    result = context_flow({'r': idx}, [{'kind': 'context', 'key': 'token'}], [])
    options = result['reference_producer_links'][0]['candidates']
    assert [c['namespace'] for c in options] == ['toolium.storage', 'behave.context']
