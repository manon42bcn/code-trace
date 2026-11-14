from coderag.hook_scope import environment_scope


def ck(path, sym, content):
    return {
        'id': path + ':' + str(sym),
        'path': path,
        'language': 'python',
        'strategy': 'python_ast' if sym else 'surrounding_code',
        'symbol': sym,
        'content': content,
        'start_line': 1,
    }


def test_local_environment_delegates_to_dependency_hook():
    local = 'features/environment.py'
    dep = 'toolium/behave/environment.py'
    indexes = {
        'app': {
            'chunks': [
                ck(
                    local,
                    None,
                    (
                        'from toolium.behave.environment import before_scenario as '
                        'base_before_scenario'
                    ),
                ),
                ck(
                    local,
                    'before_scenario',
                    (
                        'def before_scenario(context, scenario):\n    '
                        'base_before_scenario(context, scenario)'
                    ),
                ),
            ]
        },
        'toolium': {
            'chunks': [
                ck(
                    dep,
                    'before_scenario',
                    (
                        'def before_scenario(context, scenario):\n    context.storage = '
                        'ChainMap({}, context.feature_storage, context.run_storage)'
                    ),
                )
            ]
        },
    }
    lifecycle = [
        {
            'repository': 'toolium',
            'path': dep,
            'hook': 'before_scenario',
            'effect': 'chainmap_rebind',
        }
    ]
    result = environment_scope(indexes, 'features/demo.feature', 'app', lifecycle)
    assert result['entry_environment'] == local
    assert any(
        e['effect'] == 'chainmap_rebind' and len(e['hook_chain']) == 2
        for e in result['lifecycle_events']
    )
    assert result['runtime_verified'] is False


def test_nearest_environment_selected():
    indexes = {
        'app': {
            'chunks': [
                ck('features/environment.py', 'before_all', 'def before_all(context):\n    pass'),
                ck(
                    'features/sub/environment.py',
                    'before_all',
                    'def before_all(context):\n    pass',
                ),
            ]
        }
    }
    r = environment_scope(indexes, 'features/sub/a.feature', 'app')
    assert r['entry_environment'] == 'features/sub/environment.py'


def test_star_reexport_unique_local_suffix():
    indexes = {
        'app': {
            'chunks': [
                ck('acceptance/features/environment.py', None, 'from common.environment import *'),
                ck(
                    'acceptance/common/environment.py',
                    'before_all',
                    'def before_all(context):\n    pass',
                ),
            ]
        }
    }
    r = environment_scope(indexes, 'acceptance/features/a.feature', 'app')
    assert any(len(h['chain']) == 2 for h in r['hooks'])


def test_never_load_dependency_hook_without_local_entry():
    indexes = {
        'toolium': {
            'chunks': [
                ck(
                    'toolium/behave/environment.py',
                    'before_all',
                    'def before_all(context):\n    pass',
                )
            ]
        },
        'app': {'chunks': []},
    }
    r = environment_scope(indexes, 'features/a.feature', 'app')
    assert r['hooks'] == []
    assert r['status'] == 'no_environment_in_feature_ancestors'
