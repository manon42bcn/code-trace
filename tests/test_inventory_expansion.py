"""Scoped filtering/grouping and Python AST inventories never execute source."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from coderag.core import index_repository
from coderag.inventory import InventoryError, inventory, markdown, page_result


def snapshot(source, language='json'):
    key = 'python_sources' if language == 'python' else 'configuration_sources'
    return {
        key: {
            'source': {
                'source': source,
                'language': language,
                'file_sha256': hashlib.sha256(source.encode()).hexdigest(),
            }
        }
    }


def test_filter_group_dedup_and_paging_have_independent_counts():
    source = json.dumps(
        {
            'tools': [
                {'name': 'a', 'team': 'one'},
                {'name': 'a', 'team': 'two'},
                {'name': 'b', 'team': 'one'},
                {'name': 'b', 'team': 'one'},
            ]
        }
    )
    index = snapshot(source)
    result = inventory(index, path='$/tools', unique_by='name', group_by='team')
    assert result['total'] == 2
    assert result['entries'] == 4
    assert result['groups'] == [
        {'value': 'one', 'entries': 3, 'total': 2},
        {'value': 'two', 'entries': 1, 'total': 1},
    ]
    page = page_result(result, limit=1, max_chars=4)
    assert page['total'] == 2
    assert len(page['groups']) == 1
    assert page['groups_pagination']['total'] == 2
    assert len(result['groups']) == 2
    filtered = inventory(index, path='$/tools', where=['team=one', 'name=b'], unique_by='name')
    assert filtered['source_entries'] == 4
    assert filtered['entries'] == 2
    assert filtered['filtered_out'] == 2
    assert filtered['total'] == 1
    assert len(filtered['items'][0]['occurrences']) == 2
    occurrence = filtered['items'][0]['occurrences'][0]
    assert occurrence['position'] == 2
    citation = occurrence['citation']
    assert source[citation['start_offset'] : citation['end_offset']] == occurrence['content']
    assert 'Filtros' in markdown(page_result(filtered))


def test_filter_has_exact_string_semantics_and_empty_results():
    index = snapshot('{"tools":[{"name":"a=b"},{"name":"ab"},{}]}')
    assert inventory(index, path='$/tools', where=['name=a=b'])['total'] == 1
    empty = inventory(index, path='$/tools', where=['name=A'])
    assert empty['complete']
    assert empty['total'] == 0
    assert empty['filtered_out'] == 3
    with pytest.raises(InventoryError, match='FIELD=VALUE'):
        inventory(index, path='$/tools', where=['name'])


@pytest.mark.parametrize(
    ('source', 'language'),
    [
        ('{"tools":[{"name":7}]}', 'json'),
        ('tools:\n  - <<: *unknown\n    name: a\n', 'yaml'),
        ('tools:\n  - name: a\n    name: b\n', 'yaml'),
        ('tools:\n  - *unknown\n', 'yaml'),
    ],
)
def test_unresolved_filter_fields_do_not_return_partial_totals(source, language):
    with pytest.raises(InventoryError):
        inventory(snapshot(source, language), path='$/tools', where=['name=a'])


def test_group_requires_resolvable_field_for_every_matching_entry():
    index = snapshot('{"tools":[{"name":"a"},{}]}')
    with pytest.raises(InventoryError, match='group identity'):
        inventory(index, path='$/tools', group_by='name')


def test_python_decorators_are_syntactic_scoped_and_never_executed():
    source = """raise RuntimeError("MUST NOT EXECUTE")
@step("a")
@step("b")
def first():
    pass
class Client:
    @behave.step("x")
    async def nested(self):
        pass
@alias("not resolved")
def alias_case(): pass
@factory().step("dynamic")
def dynamic(): pass
"""
    index = snapshot(source, 'python')
    result = inventory(index, kind='python-decorators', file='source', decorator='step')
    assert result['complete']
    assert result['total'] == 1
    assert result['entries'] == 2
    assert result['items'][0]['name'] == 'first'
    assert result['unsupported_decorator_expressions'] == 1
    assert len(result['items'][0]['occurrences']) == 2
    dotted = inventory(index, kind='python-decorators', file='source', decorator='behave.step')
    assert dotted['total'] == 1
    assert dotted['items'][0]['name'] == 'Client.nested'
    for occurrence in dotted['items'][0]['occurrences']:
        cite = occurrence['citation']
        assert source[cite['start_offset'] : cite['end_offset']] == occurrence['content']
    assert (
        inventory(index, kind='python-decorators', file='source', decorator='missing')['total'] == 0
    )


def test_python_missing_invalid_or_old_snapshot_never_returns_partial_count():
    with pytest.raises(InventoryError, match='--file'):
        inventory({}, kind='python-decorators', decorator='step')
    with pytest.raises(InventoryError, match='Reindex'):
        inventory({}, kind='python-decorators', file='a.py', decorator='step')
    with pytest.raises(InventoryError, match='parse/verify'):
        inventory(
            snapshot('def invalid(', 'python'),
            kind='python-decorators',
            file='source',
            decorator='step',
        )
    with pytest.raises(InventoryError, match='List options'):
        inventory({}, kind='python-decorators', file='a.py', decorator='step', where=['x=y'])


def test_incremental_python_snapshots_and_cli_report(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / 'repo'
    source.mkdir()
    (source / 'steps.py').write_text('@step("a")\ndef first(): pass\n')
    raw = json.loads((root / 'config.example.json').read_text())
    raw['repositories'] = {'demo': {'path': 'repo'}}
    raw['indexing']['languages'] = ['python', 'json']
    (source / 'tools.json').write_text(
        '{"tools":[{"name":"a","team":"one"},{"name":"b","team":"two"}]}'
    )
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(raw))
    index = tmp_path / 'indexes/demo.chunks.json'
    index_repository(source, index, raw)
    data = json.loads(index.read_text())
    del data['python_sources']
    index.write_text(json.dumps(data))
    index_repository(source, index, raw, incremental=True)
    data = json.loads(index.read_text())
    assert 'steps.py' in data['python_sources']
    report = tmp_path / 'report.json'
    proc = subprocess.run(
        [
            sys.executable,
            '-m',
            'coderag',
            'inventory',
            '--config',
            str(config),
            '--repo',
            'demo',
            '--kind',
            'python-decorators',
            '--file',
            'steps.py',
            '--decorator',
            'step',
            '--report',
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)['total'] == 1
    assert json.loads(report.read_text())['kind'] == 'python-decorators'

    base = [
        sys.executable,
        '-m',
        'coderag',
        'inventory',
        '--config',
        str(config),
        '--repo',
        'demo',
        '--report',
        str(report),
    ]
    proc = subprocess.run(
        [*base, '--kind', 'python-decorators', '--file', 'steps.py', '--decorator', 'step'],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(report.read_text())['total'] == 1
    proc = subprocess.run(
        [
            *base,
            '--file',
            'tools.json',
            '--path',
            '$/tools',
            '--where',
            'team=one',
            '--group-by',
            'team',
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(report.read_text())
    assert result['total'] == 1
    assert result['filtered_out'] == 1
    assert result['groups'] == [{'value': 'one', 'entries': 1, 'total': 1}]
