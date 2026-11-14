"""Inventories count full indexed lists, independently of retrieval and display budgets."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from coderag.core import index_repository
from coderag.inventory import InventoryError, inventory, markdown, page_result

ROOT = Path(__file__).resolve().parents[1]
CFG = {
    'languages': ['yaml', 'json'],
    'chunking': {
        'strategy': 'structural',
        'max_tokens': 10,
        'overlap_tokens': 0,
        'preserve_symbols': True,
        'include_parent_context': True,
        'on_missing_parser': 'error',
        'on_syntax_error': 'recover',
    },
}


def snapshot(source, language='json', file='config.json'):
    return {
        'configuration_sources': {
            file: {
                'source': source,
                'language': language,
                'file_sha256': hashlib.sha256(source.encode()).hexdigest(),
            }
        }
    }


def test_compact_json_complete_count_pagination_and_citations():
    source = json.dumps({'tools': [{'name': f'tool_{n}'} for n in range(100)]})
    full = inventory(snapshot(source), file='config.json', path='$/tools', unique_by='name')
    assert full['total'] == full['entries'] == 100
    assert full['complete']
    page = page_result(full, offset=20, limit=5, max_chars=8)
    assert page['total'] == 100
    assert len(page['items']) == 5
    assert page['pagination']['has_more']
    assert page['items'][0]['name'] == 'tool_20'
    occurrence = full['items'][20]['occurrences'][0]
    cite = occurrence['citation']
    assert cite['start_line'] == cite['end_line'] == 1
    assert source[cite['start_offset'] : cite['end_offset']] == occurrence['content']
    assert page['items'][0]['occurrences'][0]['truncated']
    assert not page_result(full, offset=200)['items']
    assert len(full['items']) == 100


def test_deduplication_is_explicit_and_preserves_all_occurrences():
    indexed = snapshot('{"tools":[{"name":"a"},{"name":"a"},{"name":"b"}]}')
    assert inventory(indexed, path='$/tools')['total'] == 3
    full = inventory(indexed, path='$/tools', unique_by='name')
    assert full['total'] == 2
    assert full['entries'] == 3
    assert full['duplicates'] == 1
    assert len(full['items'][0]['occurrences']) == 2
    page = page_result(full, max_occurrences=1)
    assert page['items'][0]['occurrences_total'] == 2
    assert page['items'][0]['occurrences_truncated']
    assert len(full['items'][0]['occurrences']) == 2


def test_missing_identity_does_not_return_a_partial_count():
    indexed = snapshot('{"tools":[{"name":"a"},{"unknown":"b"}]}')
    with pytest.raises(InventoryError, match='no partial count') as exc:
        inventory(indexed, path='$/tools', unique_by='name')
    assert exc.value.code == 'identity_unresolved'


def test_empty_list_is_complete_zero():
    result = inventory(snapshot('{"tools":[]}'), path='$/tools')
    assert result['total'] == 0
    assert result['complete']
    assert result['items'] == []


def test_discovery_requires_scope_when_multiple_lists_match():
    result = inventory(snapshot('{"one":[1],"two":[2,3]}'))
    assert result['status'] == 'needs_scope'
    assert not result['complete']
    assert result['total'] is None
    assert len(page_result(result, limit=1)['scopes']) == 1
    assert inventory(snapshot('{"one":[1],"two":[2,3]}'), path='$/two')['total'] == 2


def test_yaml_multidoc_and_aliases_are_not_expanded():
    source = '---\ntools: [a, b]\n---\ntools: &base [x]\ncopy: *base\n'
    indexed = snapshot(source, 'yaml', 'agent.yaml')
    assert inventory(indexed, path='$doc/0/tools')['total'] == 2
    assert inventory(indexed, path='$doc/1/tools')['total'] == 1
    with pytest.raises(InventoryError, match='No valid list') as exc:
        inventory(indexed, path='$doc/1/copy')
    assert exc.value.code == 'scope_not_list'


def test_invalid_snapshots_and_old_indexes_fail_explicitly():
    with pytest.raises(InventoryError, match='Rebuild indexes'):
        inventory({'chunks': []})
    for indexed in (snapshot('{'), snapshot('{"tools":[],"tools":[]}')):
        with pytest.raises(InventoryError, match='No valid list') as exc:
            inventory(indexed)
        assert exc.value.code == 'snapshot_invalid'
    tampered = snapshot('[1,2]')
    tampered['configuration_sources']['config.json']['source'] = '[9]'
    with pytest.raises(InventoryError, match='No valid list'):
        inventory(tampered)


def test_inventory_uses_indexed_snapshot_until_reindexed(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    source = repo / 'agent.yaml'
    source.write_text('agent:\n  tools:\n    - name: first\n    - name: second\n')
    target = tmp_path / 'index.json'
    indexed = index_repository(repo, target, {'indexing': CFG})
    assert inventory(indexed, path='$/agent/tools')['total'] == 2
    same = index_repository(repo, target, {'indexing': CFG}, incremental=True)
    assert same['configuration_sources'] == indexed['configuration_sources']
    source.write_text('agent:\n  tools: []\n')
    assert inventory(indexed, path='$/agent/tools')['total'] == 2
    updated = index_repository(repo, target, {'indexing': CFG}, incremental=True)
    assert inventory(updated, path='$/agent/tools')['total'] == 0


def test_cli_full_report_is_not_paginated_and_inventory_is_offline(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'agent.json').write_text(json.dumps({'tools': [{'name': str(n)} for n in range(30)]}))
    index_repository(repo, tmp_path / 'indexes/demo.chunks.json', {'indexing': CFG})
    (tmp_path / 'src').symlink_to(ROOT / 'src', target_is_directory=True)
    (tmp_path / '.venv').symlink_to(ROOT / '.venv', target_is_directory=True)
    config = tmp_path / 'config.json'
    config.write_text(
        json.dumps({'repositories': {'demo': {'path': 'repo'}}, 'generation': {'provider': 'none'}})
    )
    report = tmp_path / 'report.json'
    command = [
        sys.executable,
        '-m',
        'coderag',
        'inventory',
        '--config',
        str(config),
        '--repo',
        'demo',
        '--file',
        'agent.json',
        '--path',
        '$/tools',
        '--unique-by',
        'name',
        '--limit',
        '2',
        '--report',
        str(report),
    ]
    proc = subprocess.run(command, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    output = json.loads(proc.stdout)
    assert output['total'] == 30
    assert len(output['items']) == 2
    assert len(json.loads(report.read_text())['items']) == 30
    proc = subprocess.run([*command, '--output-format', 'markdown'], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '**Total:** 30' in proc.stdout
    assert 'Página: 2 de 30' in proc.stdout


def test_markdown_preserves_source_fences_and_marks_clipping():
    full = inventory(snapshot('["```","two"]'))
    output = page_result(full, max_chars=2)
    text = markdown(output)
    assert 'Fragmento truncado' in text
    assert full['total'] == 2
