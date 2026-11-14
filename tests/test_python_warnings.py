"""Python warnings retain source locations through workers, reuse and derived AST passes."""

import json
import subprocess
import sys
import warnings

import pytest

from coderag.core import index_repository, python_units
from coderag.python_parsing import parse_python

SOURCE = (
    '# header\n'
    'class First:\n'
    '    """acceptance\\common\\steps"""\n'
    '    def step(self):\n'
    '        return 1\n'
    '\n'
    'class Second:\n'
    '    """acceptance\\common\\steps"""\n'
    '    def step(self):\n'
    '        return 2\n'
)
SETTINGS = {
    'languages': ['python'],
    'chunking': {
        'strategy': 'structural',
        'max_tokens': 100,
        'overlap_tokens': 0,
        'preserve_symbols': True,
        'include_parent_context': True,
        'on_missing_parser': 'error',
    },
}


@pytest.fixture
def prepared(tmp_path):
    repo = tmp_path / 'repo with spaces'
    repo.mkdir()
    file = repo / 'example.py'
    file.write_text(SOURCE)
    config = {'repositories': {'demo': {'path': str(repo)}}, 'indexing': SETTINGS}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    output = tmp_path / 'indexes/demo.chunks.json'
    return repo, file, config, path, output


@pytest.mark.parametrize('isolated', [False, True])
def test_cli_prints_original_file_locations_once_and_saves_diagnostics(prepared, isolated):
    repo, file, config, path, output = prepared
    config['indexing'] = {**SETTINGS, 'isolate_parsers': isolated}
    path.write_text(json.dumps(config))
    command = [sys.executable, '-m', 'coderag', 'index', '--config', str(path), '--repo', 'demo']
    for extra in ([], ['--incremental']):
        proc = subprocess.run([*command, *extra], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert '<unknown>' not in proc.stderr
        assert proc.stderr.count('invalid escape sequence') == 2
        assert f'{file}:3:' in proc.stderr
        assert f'{file}:8:' in proc.stderr
        data = json.loads(output.read_text())
        found = [d for d in data['diagnostics'] if d.get('type') == 'python_syntax_warning']
        assert len(found) == 2
        assert [d['line'] for d in found] == [3, 8]
        assert all(d['path'] == 'example.py' and d['severity'] == 'warning' for d in found)
        assert data['files_discovered'] == 1
        assert not data['skipped_files']
        assert repo.exists()


def test_library_does_not_repeat_snippet_warnings_and_keeps_source_unchanged(prepared):
    repo, file, config, _, output = prepared
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        result = index_repository(repo, output, config)
    assert not [w for w in captured if 'invalid escape sequence' in str(w.message)]
    assert len(result['diagnostics']) == 2
    assert result['chunks']
    assert file.read_text() == SOURCE


def test_legacy_incremental_index_backfills_and_then_reuses_warnings(prepared):
    repo, _, config, _, output = prepared
    first = index_repository(repo, output, config)
    legacy = {**first, 'diagnostics': []}
    legacy.pop('python_diagnostics_version')
    output.write_text(json.dumps(legacy))
    progress = []
    upgraded = index_repository(repo, output, config, incremental=True, progress=progress.append)
    assert len(upgraded['diagnostics']) == 2
    assert not any(line.startswith('REUSE') for line in progress)
    progress.clear()
    reused = index_repository(repo, output, config, incremental=True, progress=progress.append)
    assert reused['diagnostics'] == upgraded['diagnostics']
    assert reused['chunks'] == first['chunks']
    assert any(line.startswith('REUSE') for line in progress)


def test_fixed_and_deleted_files_drop_old_warnings(prepared):
    repo, file, config, _, output = prepared
    index_repository(repo, output, config)
    file.write_text(SOURCE.replace('"""acceptance', 'r"""acceptance'))
    assert not index_repository(repo, output, config, incremental=True)['diagnostics']
    file.unlink()
    assert not index_repository(repo, output, config, incremental=True)['diagnostics']


def test_standalone_parser_reports_supplied_filename():
    with warnings.catch_warnings(record=True) as found:
        warnings.simplefilter('always')
        python_units(SOURCE, filename='actual/example.py')
    assert len(found) == 2
    assert all(w.filename == 'actual/example.py' for w in found)
    assert [w.lineno for w in found] == [3, 8]


@pytest.mark.parametrize('category', [UserWarning, DeprecationWarning])
def test_quiet_snippet_parse_preserves_unrelated_warning_categories(monkeypatch, category):
    import coderag.python_parsing as parsing

    original = parsing.ast.parse

    def noisy(source, *, filename):
        warnings.warn('unrelated library warning', category, stacklevel=1)
        return original(source, filename=filename)

    monkeypatch.setattr(parsing.ast, 'parse', noisy)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        tree = parse_python(SOURCE, quiet=True)
    assert tree.body
    assert len(captured) == 1
    assert captured[0].category is category
    assert str(captured[0].message) == 'unrelated library warning'
