import json

from coderag.behave_links import build_behave_relations
from coderag.repo_links import build_repository_links, save_links


def _make_index(root, name, chunks):
    (root / 'indexes').mkdir(exist_ok=True)
    path = root / 'indexes' / f'{name}.chunks.json'
    path.write_text(
        json.dumps(
            {
                'chunks': chunks,
                'created_at': '2026-10-24',
                'source_root': name,
                'behave_relations': build_behave_relations(chunks),
            }
        )
    )
    return path


def _func(name, path, pattern):
    return {
        'id': name,
        'path': path,
        'language': 'python',
        'strategy': 'python_ast',
        'symbol': name,
        'start_line': 1,
        'content': f'@given({pattern!r})\ndef {name}(context):\n pass',
    }


def test_scope_prevents_false_ambiguity(tmp_path):
    chunks = [
        {
            'id': 's',
            'path': 'web_behave/features/login.feature',
            'language': 'gherkin',
            'symbol': 'scenario: X',
            'start_line': 1,
            'content': 'Scenario: X\n Given login page open',
        },
        _func('web', 'web_behave/steps/login.py', 'login page open'),
        _func('playwright', 'web_playwright_behave/steps/login.py', 'login page open'),
    ]
    _make_index(tmp_path, 'test', chunks)
    cfg = {'repositories': {'test': {}}}
    rel = build_repository_links(cfg, tmp_path / 'cfg.json', 'test')
    assert rel['summary']['resolved_local'] == 1
    assert rel['relations'][0]['definitions'][0]['function'] == 'web'


def test_dependency_link_and_missing(tmp_path):
    chunks = [
        {
            'id': 's',
            'path': 'features/test.feature',
            'language': 'gherkin',
            'symbol': 'scenario: S',
            'start_line': 1,
            'content': 'Scenario: S\n Given shared hello',
        }
    ]
    _make_index(tmp_path, 'app', chunks)
    _make_index(tmp_path, 'lib', [_func('shared', 'lib/steps.py', 'shared hello')])
    cfg = {
        'repositories': {
            'app': {},
            'lib': {},
            'missing': {},
        },
        'relationships': {'app': {'dependencies': ['lib', 'missing']}},
    }
    linked = build_repository_links(cfg, tmp_path / 'cfg.json', 'app')
    assert linked['summary']['resolved_external'] == 1
    assert linked['summary']['missing_dependencies'] == 1
    assert linked['relations'][0]['definitions'][0]['repository'] == 'lib'
    out = tmp_path / 'linked.json'
    save_links(out, linked)
    assert json.loads(out.read_text())['summary'] == linked['summary']


def test_repeated_steps_reuse_compiled_patterns(tmp_path, monkeypatch):
    from coderag import repo_links

    steps = '\n'.join(' Given shared hello' for _ in range(100))
    chunks = [
        {
            'id': 's',
            'path': 'features/test.feature',
            'language': 'gherkin',
            'symbol': 'scenario: S',
            'start_line': 1,
            'content': 'Scenario: S\n' + steps,
        }
    ]
    _make_index(tmp_path, 'app', chunks)
    _make_index(tmp_path, 'lib', [_func('shared', 'lib/steps.py', 'shared hello')])
    cfg = {
        'repositories': {'app': {}, 'lib': {}},
        'relationships': {'app': {'dependencies': ['lib']}},
    }
    orig = repo_links._matches
    calls = []

    def counted(*args):
        calls.append(1)
        return orig(*args)

    monkeypatch.setattr(repo_links, '_matches', counted)
    result = build_repository_links(cfg, tmp_path / 'cfg.json', 'app')
    assert result['summary']['resolved_external'] == 100
    assert len(calls) == 2  # once local and once external


def test_custom_step_roots_and_export_filter(tmp_path):
    feature = [
        {
            'id': 's',
            'path': 'acceptance/features/a.feature',
            'language': 'gherkin',
            'symbol': 'scenario: S',
            'start_line': 1,
            'content': 'Scenario: S\n Given own step\n Given remote step',
        }
    ]
    _make_index(
        tmp_path, 'app', [*feature, _func('own', 'acceptance/common/steps/shared.py', 'own step')]
    )
    _make_index(
        tmp_path,
        'lib',
        [
            _func('remote', 'package/behave/steps/api.py', 'remote step'),
            _func('bad', 'examples/steps/other.py', 'remote step'),
        ],
    )
    cfg = {
        'repositories': {'app': {}, 'lib': {}},
        'relationships': {
            'app': {
                'dependencies': ['lib'],
                'behave_scopes': [
                    {'features': 'acceptance/features', 'steps': ['acceptance/common/steps']}
                ],
            },
            'lib': {'exported_steps': ['package/behave/steps']},
        },
    }
    report = build_repository_links(cfg, tmp_path / 'config.json', 'app')
    assert report['summary']['resolved_local'] == 1
    assert report['summary']['resolved_external'] == 1
    assert report['summary']['ambiguous'] == 0
    assert report['relations'][1]['definitions'][0]['function'] == 'remote'


def test_multiple_decorators_one_function_is_not_ambiguous(tmp_path):
    feature = [
        {
            'id': 's',
            'path': 'features/x.feature',
            'language': 'gherkin',
            'symbol': 'scenario: S',
            'start_line': 1,
            'content': 'Scenario: S\n Given value is 42',
        }
    ]
    code = '@given("value is {x:d}")\n@given("value is {x}")\ndef shared(context, x):\n pass'
    chunk = {
        'id': 'shared',
        'path': 'features/steps/a.py',
        'language': 'python',
        'strategy': 'python_ast',
        'symbol': 'shared',
        'start_line': 1,
        'content': code,
    }
    _make_index(tmp_path, 'app', [*feature, chunk])
    cfg = {'repositories': {'app': {}}}
    res = build_repository_links(cfg, tmp_path / 'config.json', 'app')
    assert res['summary']['resolved_local'] == 1
    assert len(res['relations'][0]['definitions']) == 1
