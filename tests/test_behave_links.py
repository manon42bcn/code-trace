from coderag.behave_links import build_behave_relations
from coderag.core import index_repository

CFG = {
    'languages': ['python', 'gherkin'],
    'language_overrides': {},
    'chunking': {
        'strategy': 'structural',
        'max_tokens': 1024,
        'overlap_tokens': 128,
        'preserve_symbols': True,
        'include_parent_context': True,
        'on_missing_parser': 'error',
        'on_syntax_error': 'recover',
    },
}


def test_resolve_parameter_and_and(tmp_path):
    root = tmp_path / 'repo'
    (root / 'features' / 'steps').mkdir(parents=True)
    (root / 'features' / 'login.feature').write_text(
        'Feature: Login\n  Scenario: login\n    Given user signs in\n    And user sees "Ada"\n'
    )
    (root / 'features' / 'steps' / 'steps.py').write_text(
        "from behave import given\n@given('user signs in')\ndef "
        'signin(context):\n pass\n@given(\'user sees "{name}"\')\ndef '
        'see(context,name):\n pass\n'
    )
    index = index_repository(root, tmp_path / 'idx.json', {'indexing': CFG})
    r = index['behave_relations']
    assert r['summary']['step_occurrences'] == 2
    assert r['summary']['resolved'] == 2
    assert r['step_occurrences'][1]['effective_keyword'] == 'given'


def test_ambiguous_does_not_choose():
    chunks = [
        {
            'id': 'f',
            'path': 'a.feature',
            'language': 'gherkin',
            'symbol': 'scenario: X',
            'start_line': 1,
            'content': 'Scenario: X\n Given hello',
        },
        *[
            {
                'id': str(i),
                'path': f'steps{i}.py',
                'language': 'python',
                'strategy': 'python_ast',
                'symbol': f'f{i}',
                'start_line': 1,
                'content': "@given('hello')\ndef hello(context):\n pass",
            }
            for i in range(2)
        ],
    ]
    r = build_behave_relations(chunks)
    assert r['summary']['ambiguous'] == 1
    assert len(r['step_occurrences'][0]['definitions']) == 2


def test_isolation_timeout_and_errors(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'x.py').write_text('def f():\n return 1\n')
    out = tmp_path / 'idx.json'
    settings = {**CFG, 'isolate_parsers': True, 'timeout_seconds': 10, 'on_file_error': 'error'}
    index = index_repository(root, out, {'indexing': settings})
    assert index['files_discovered'] == 1
    assert index['chunks']
