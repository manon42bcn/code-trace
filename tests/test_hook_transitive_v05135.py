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


def test_aicc_retry_indirection_to_toolium_hook():
    src = 'features/environment.py'
    helper = 'common/environment.py'
    dep = 'toolium/behave/environment.py'
    indexes = {
        'app': {
            'chunks': [
                ck(src, None, 'from common.environment import *'),
                ck(
                    helper,
                    None,
                    (
                        'from toolium.behave.environment import before_scenario as '
                        'toolium_before_scenario'
                    ),
                ),
                ck(
                    helper,
                    'before_scenario',
                    (
                        'def before_scenario(context, scenario):\n    try:\n        '
                        '_retry(context, scenario)\n    except Exception:\n        raise'
                    ),
                ),
                ck(
                    helper,
                    '_retry',
                    (
                        '@retry(max_attempts=3)\ndef _retry(context, scenario):\n    '
                        'toolium_before_scenario(context, scenario)'
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
                        'ChainMap({}, context.feature_storage)'
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
    result = environment_scope(indexes, 'features/foo.feature', 'app', lifecycle)
    matches = [e for e in result['lifecycle_events'] if e['effect'] == 'chainmap_rebind']
    assert len(matches) == 1
    assert len(matches[0]['hook_chain']) == 4
    assert matches[0]['reachability'] == 'conditional_static'
    assert {'decorated_helper', 'conditional_control_flow'} <= set(matches[0]['conditions'])
    assert matches[0]['runtime_verified'] is False


def test_simple_helper_chain_preserves_static_reachable():
    path = 'features/environment.py'
    indexes = {
        'app': {
            'chunks': [
                ck(path, 'before_all', 'def before_all(context):\n    init(context)'),
                ck(path, 'init', 'def init(context):\n    context.run_storage = {}'),
            ]
        }
    }
    lifecycle = [{'repository': 'app', 'path': path, 'hook': 'init', 'effect': 'new_empty_dict'}]
    r = environment_scope(indexes, 'features/foo.feature', 'app', lifecycle)
    assert r['lifecycle_events'][0]['reachability'] == 'static_reachable'
    assert r['lifecycle_events'][0]['conditions'] == []


def test_non_called_helper_not_reachable():
    path = 'features/environment.py'
    indexes = {
        'app': {
            'chunks': [
                ck(path, 'before_all', 'def before_all(context):\n    pass'),
                ck(path, 'other', 'def other(context):\n    context.run_storage = {}'),
            ]
        }
    }
    lifecycle = [{'repository': 'app', 'path': path, 'hook': 'other', 'effect': 'new_empty_dict'}]
    r = environment_scope(indexes, 'features/foo.feature', 'app', lifecycle)
    assert not r['lifecycle_events']
