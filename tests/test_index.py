import json
from pathlib import Path

import pytest

from coderag.core import (
    build_chunks,
    detect_language,
    index_repository,
)

CFG = {
    'chunking': {
        'strategy': 'structural',
        'max_tokens': 40,
        'overlap_tokens': 5,
        'preserve_symbols': True,
        'include_parent_context': True,
        'on_missing_parser': 'error',
    },
    'languages': ['python', 'c', 'cpp', 'makefile', 'shell', 'lock'],
    'language_overrides': {'.h': 'cpp'},
}


def test_detect():
    assert detect_language(Path('hello.cpp'), {}) == 'cpp'
    assert detect_language(Path('Makefile'), {}) == 'makefile'
    assert detect_language(Path('package-lock.json'), {}) == 'lock'
    assert detect_language(Path('header.h'), {'.h': 'cpp'}) == 'cpp'


def test_python_symbol():
    src = 'class A:\n    def f(self):\n        return 3\n\nx = 1\n'
    chunks = build_chunks('a.py', 'python', src, CFG)
    assert any(c['symbol'] == 'A.f' for c in chunks)
    assert any(c['symbol'] == 'A' for c in chunks)
    assert all(c['estimated_tokens'] <= 40 for c in chunks)


def test_preserves_small_function():
    src = 'def test(a):\n    b = a + 1\n    return b\n'
    chunks = build_chunks('a.py', 'python', src, CFG)
    assert len(chunks) == 1
    assert chunks[0]['symbol'] == 'test'


def test_long_unit_is_bounded():
    src = 'def long():\n' + ''.join(f'    x{i} = {i} + 100\n' for i in range(100))
    chunks = build_chunks('a.py', 'python', src, CFG)
    assert len(chunks) > 1
    assert all(c['estimated_tokens'] <= 40 for c in chunks)
    assert all(c['symbol'] == 'long' for c in chunks)


def test_minified_long_line():
    src = 'x = ' + ('abcd+' * 180)
    chunks = build_chunks('x.lock', 'lock', src, CFG)
    assert len(chunks) > 1
    assert all(c['estimated_tokens'] <= 40 for c in chunks)


def test_missing_parser_fails_loudly(monkeypatch):
    import coderag.core as core

    def unavailable(*_args, **_kwargs):
        raise ValueError('parser missing')

    monkeypatch.setattr(core, 'treesitter_units', unavailable)
    with pytest.raises(ValueError, match='parser missing'):
        build_chunks('hi.cpp', 'cpp', 'int f() { return 1; }', CFG)


def test_index(tmp_path):
    project = tmp_path / 'repo'
    project.mkdir()
    (project / 'a.py').write_text('def f():\n    return 1\n', encoding='utf8')
    (project / 'Makefile').write_text('test:\n\techo yes\n', encoding='utf8')
    out = tmp_path / 'idx.json'
    result = index_repository(project, out, {'indexing': CFG})
    assert out.exists()
    assert result['files_discovered'] == 2
    assert json.loads(out.read_text())['schema_version'] == 2


def test_makefile():
    s = 'build:\n\tcc main.c\n\ntest:\n\t./a.out\n'
    c = build_chunks('Makefile', 'makefile', s, CFG)
    assert any(x['symbol'] == 'build' for x in c)
    assert any(x['symbol'] == 'test' for x in c)


def test_gherkin_scenarios_and_outlines():
    src = (
        'Feature: Login\n  @smoke\n  Scenario: Valid\n    Given a user\n   '
        ' Then success\n  Scenario Outline: Invalid\n    When I enter '
        '<password>\n    Examples:\n      | password |\n      | wrong |\n'
    )
    chunks = build_chunks('login.feature', 'gherkin', src, CFG)
    assert any(
        'scenario: Valid' in c['symbol'] and '@smoke' in c['content'] for c in chunks if c['symbol']
    )
    assert any(
        'scenario_outline: Invalid' in c['symbol'] and 'wrong' in c['content']
        for c in chunks
        if c['symbol']
    )


def test_python_decorator_stays_with_method():
    src = 'class A:\n    @staticmethod\n    def f():\n        return 1\n'
    chunks = build_chunks('a.py', 'python', src, CFG)
    assert any(c['symbol'] == 'A.f' and '@staticmethod' in c['content'] for c in chunks)
    assert not any(c['content'].strip() == '@staticmethod' for c in chunks)


def test_report():
    from coderag.core import analyze_index

    chunks = build_chunks('x.feature', 'gherkin', 'Feature: hello\nScenario: a\n Given foo\n', CFG)
    report = analyze_index({'chunks': chunks, 'chunking': CFG['chunking'], 'files_discovered': 1})
    assert report['files_indexed'] == 1
    assert report['over_budget'] == 0


def test_doctext_adjacent_c_function():
    from coderag.core import attach_leading_docs

    lines = ['/**', ' * Description', ' */', 'int answer(void) {', 'return 42;', '}']
    assert attach_leading_docs(lines, [(4, 6, 'answer', 'tree_sitter')], 'c')[0][0] == 1


def test_exclusions_global_and_repo_cli(tmp_path):
    from coderag.core import is_excluded

    assert is_excluded('websrv/data/docs/html/search/search.js', ['**/docs/html/**'])
    assert is_excluded('docs/html/a.js', ['**/docs/html/**'])
    assert not is_excluded('src/html/search.js', ['**/docs/html/**'])
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'keep.py').write_text('def ok():\n    return True\n')
    demo = repo / 'tests' / 'demo'
    demo.mkdir(parents=True)
    (demo / 'skip.py').write_text('def no():\n    return False\n')
    generated = repo / 'generated'
    generated.mkdir()
    (generated / 'skip.py').write_text('def no():\n    return False\n')
    output = tmp_path / 'index.json'
    res = index_repository(
        repo, output, {'indexing': {**CFG, 'exclude': ['tests/demo/**']}}, excludes=['generated/**']
    )
    assert res['files_discovered'] == 1
    assert {c['path'] for c in res['chunks']} == {'keep.py'}
    assert {x['path'] for x in res['excluded_paths']} == {'tests/demo', 'generated'}
    assert output.exists()


def test_exclude_cli(tmp_path):
    import subprocess
    import sys

    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'a.py').write_text('def good():\n    return 1\n')
    (repo / 'generated').mkdir()
    (repo / 'generated' / 'z.py').write_text('def bad():\n    return 1\n')
    cfg = {
        'default_repository': 'r',
        'repositories': {'r': {'path': 'repo', 'exclude': ['generated/**']}},
        'indexing': CFG,
    }
    (tmp_path / 'config.json').write_text(json.dumps(cfg))
    r = subprocess.run(
        [
            sys.executable,
            '-m',
            'coderag',
            'index',
            '--config',
            str(tmp_path / 'config.json'),
            '--repo',
            'r',
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads((tmp_path / 'indexes/r.chunks.json').read_text())
    assert {c['path'] for c in data['chunks']} == {'a.py'}


@pytest.mark.parametrize('syntax_error', [False, True])
def test_tree_sitter_coordinates_use_tuple_access(monkeypatch, syntax_error):
    """Point attributes in tree-sitter 0.26.0 can corrupt native reference counts."""
    import sys
    from types import SimpleNamespace

    from coderag.core import treesitter_units

    class Point(tuple):
        @property
        def row(self):
            pytest.fail('Use tuple indexing instead of the faulty Point.row accessor')

        @property
        def column(self):
            pytest.fail('Use tuple indexing instead of the faulty Point.column accessor')

    child = SimpleNamespace(
        type='ERROR' if syntax_error else 'function_declaration',
        has_error=syntax_error,
        is_missing=False,
        start_point=Point((300, 7)),
        end_point=Point((302, 9)),
        children=[],
        named_children=[],
        child_by_field_name=lambda _name: None,
    )
    root = SimpleNamespace(
        type='program',
        has_error=syntax_error,
        is_missing=False,
        children=[child],
        named_children=[child],
    )
    parser = SimpleNamespace(parse=lambda _source: SimpleNamespace(root_node=root))
    monkeypatch.setitem(
        sys.modules,
        'tree_sitter_language_pack',
        SimpleNamespace(get_parser=lambda _language: parser),
    )
    diagnostics = []
    units = treesitter_units('source', 'javascript', recover=True, diagnostics=diagnostics)
    if syntax_error:
        assert units == []
        assert diagnostics[0]['line'] == 301
        assert diagnostics[0]['column'] == 8
        assert diagnostics[0]['end_line'] == 303
    else:
        assert units == [(301, 303, 'function_declaration', 'tree_sitter')]
