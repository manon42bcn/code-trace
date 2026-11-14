"""Check JSON validation and repository discovery without rewriting input files."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/lint_json.py'
spec = importlib.util.spec_from_file_location('lint_json', SCRIPT)
linter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linter)


@pytest.mark.parametrize(
    ('content', 'message'),
    [
        ('{"key": }', 'line 1 column'),
        ('{"key": 1, "key": 2}', 'Duplicate object key'),
        ('{"nested": {"key": 1, "key": 2}}', 'Duplicate object key'),
        ('{"number": NaN}', 'Non-standard JSON number'),
        ('{"number": Infinity}', 'Non-standard JSON number'),
        ('{"number": -Infinity}', 'Non-standard JSON number'),
    ],
)
def test_invalid_json_reports_error_without_modifying_file(tmp_path, content, message):
    path = tmp_path / 'invalid.json'
    path.write_text(content)
    proc = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
    assert proc.returncode == 1
    assert message in proc.stderr
    assert path.read_text() == content


def test_reports_all_files_and_keeps_valid_json_unchanged(tmp_path):
    valid = tmp_path / 'valid.json'
    invalid = tmp_path / 'invalid.json'
    valid.write_text('{ "español": [true, null, 1.5] }')
    invalid.write_text('{')
    assert linter.main([str(invalid), str(valid)]) == 1
    assert valid.read_text() == '{ "español": [true, null, 1.5] }'
    assert linter.main([str(valid)]) == 0


def test_discovery_includes_json_examples_but_excludes_generated_and_ignored(tmp_path, monkeypatch):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_text('local.json\nindexes/\n')
    (tmp_path / 'tracked.json').write_text('{}')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'tracked.json'], check=True)
    for filename in (
        'local.json',
        'untracked.json',
        'indexes/data.json',
        'dry_run/data.json',
        'examples/fixture.json',
    ):
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
    monkeypatch.setattr(linter, 'ROOT', tmp_path)
    assert {path.relative_to(tmp_path).as_posix() for path in linter.discover_files()} == {
        'tracked.json',
        'untracked.json',
        'examples/fixture.json',
    }
