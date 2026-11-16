"""Read-only diagnostics detect stale sources/artifacts without invoking models."""

import json
import subprocess
import sys

import pytest

from coderag.artifact_state import link_signature
from coderag.core import index_repository
from coderag.doctor import diagnose


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a.json').write_text('{"a": []}')
    config = {
        'repositories': {'demo': {'path': 'source'}},
        'indexing': {
            'languages': ['json'],
            'chunking': {
                'strategy': 'structural',
                'max_tokens': 100,
                'overlap_tokens': 0,
                'on_missing_parser': 'error',
                'preserve_symbols': True,
                'include_parent_context': True,
            },
        },
        'generation': {'provider': 'invalid-do-not-load'},
    }
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    index = tmp_path / 'indexes/demo.chunks.json'
    index_repository(source, index, config)
    data = json.loads(index.read_text())
    links = tmp_path / 'indexes/demo.relationships.json'
    links.write_text(
        json.dumps(
            {
                'evidence_graph': {},
                'index_sources': {'demo': {'created_at': data['created_at']}},
                'preparation_signature': link_signature(config, 'demo'),
            }
        )
    )
    return path, source, index, links


def checks(result, code):
    return [c for c in result['checks'] if c['code'] == code]


def test_full_ready_without_generation_or_writes(prepared):
    path, _, index, links = prepared
    before = (index.read_bytes(), links.read_bytes())
    result = diagnose(path, full=True)
    assert result['status'] == 'ok'
    assert checks(result, 'freshness')[0]['status'] == 'ok'
    assert checks(result, 'provider')[0]['status'] == 'skipped'
    assert before == (index.read_bytes(), links.read_bytes())


@pytest.mark.parametrize('change', ['add', 'delete', 'edit', 'settings'])
def test_full_detects_source_or_settings_changes(prepared, change):
    path, source, _, _ = prepared
    if change == 'add':
        (source / 'empty.json').write_text('{}')
    elif change == 'delete':
        (source / 'a.json').unlink()
    elif change == 'edit':
        (source / 'a.json').write_text('{"b": []}')
    else:
        raw = json.loads(path.read_text())
        raw['indexing']['exclude'] = ['not-present/**']
        path.write_text(json.dumps(raw))
    result = diagnose(path, full=True)
    assert checks(result, 'freshness')[0]['status'] == 'error'
    assert '--incremental' in checks(result, 'freshness')[0]['remedy']


def test_legacy_and_quick_do_not_claim_full_freshness(prepared):
    path, _, index, _ = prepared
    data = json.loads(index.read_text())
    del data['source_manifest']
    index.write_text(json.dumps(data))
    assert checks(diagnose(path, full=True), 'freshness')[0]['status'] == 'warning'
    assert checks(diagnose(path), 'freshness_scope')[0]['status'] == 'warning'


def test_invalid_links_and_missing_vectors(prepared):
    path, _, _, links = prepared
    links.write_text('{"evidence_graph": {}}')
    raw = json.loads(path.read_text())
    raw['retrieval'] = {'semantic_enabled': True}
    path.write_text(json.dumps(raw))
    result = diagnose(path, full=True)
    assert checks(result, 'relationships')[0]['status'] == 'error'
    assert checks(result, 'vectors')[0]['status'] == 'error'


def test_bad_config_and_unknown_repository(prepared):
    path, _, _, _ = prepared
    assert diagnose(path, repos=['unknown'])['status'] == 'error'
    path.write_text('[]')
    assert diagnose(path)['status'] == 'error'


def test_cli_exit_json_and_optional_probe(prepared, monkeypatch):
    path, _, _, _ = prepared
    from coderag import provider_check

    calls = []
    monkeypatch.setattr(
        provider_check, 'check_provider', lambda raw, **kwargs: calls.append((raw, kwargs))
    )
    assert checks(diagnose(path, full=True, probe=True), 'provider')[0]['status'] == 'ok'
    assert len(calls) == 1
    proc = subprocess.run(
        [
            sys.executable,
            '-m',
            'coderag',
            'doctor',
            '--config',
            str(path),
            '--repo',
            'unknown',
            '--output-format',
            'json',
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert json.loads(proc.stdout)['status'] == 'error'


def test_stale_dependency_and_wrong_source(prepared):
    path, _, index, links = prepared
    data = json.loads(links.read_text())
    data['index_sources']['demo']['created_at'] = 'old'
    links.write_text(json.dumps(data))
    assert checks(diagnose(path, full=True), 'relationships')[0]['status'] == 'error'
    data = json.loads(index.read_text())
    data['source_root'] = str(path.parent / 'wrong')
    index.write_text(json.dumps(data))
    assert checks(diagnose(path, full=True), 'index')[0]['status'] == 'error'


def test_full_ignores_excluded_source_and_tracks_empty_files(prepared):
    path, source, index, _ = prepared
    (source / '.hidden').mkdir()
    (source / '.hidden/secret.json').write_text('{}')
    (source / 'notes.txt').write_text('not an indexed language')
    assert checks(diagnose(path, full=True), 'freshness')[0]['status'] == 'ok'
    (source / 'empty.json').write_text('')
    raw = json.loads(path.read_text())
    index_repository(source, index, raw, incremental=True)
    data = json.loads(index.read_text())
    assert 'empty.json' in data['source_manifest']
    assert checks(diagnose(path, full=True), 'freshness')[0]['status'] == 'ok'


def test_optional_provider_failure_is_actionable(prepared, monkeypatch):
    path, _, _, _ = prepared
    from coderag import provider_check

    def fail(*_args, **_kwargs):
        raise provider_check.ProviderCheckError('connection_failed', 'Service unavailable')

    monkeypatch.setattr(provider_check, 'check_provider', fail)
    result = diagnose(path, probe=True)
    assert checks(result, 'provider')[0]['status'] == 'error'
    assert 'connection_failed' in checks(result, 'provider')[0]['message']


def test_vector_metadata_dimensions_and_coverage(prepared):
    path, _, index, _ = prepared
    raw = json.loads(path.read_text())
    raw['retrieval'] = {'semantic_enabled': True, 'embedding_model': 'test-model'}
    path.write_text(json.dumps(raw))
    chunks = json.loads(index.read_text())['chunks']
    payload = {
        'metadata': {'model_id': 'test-model', 'dimensions': 2, 'config_version': '1'},
        'records': {c['id']: {'vector': [1.0, 0.0]} for c in chunks},
    }
    for version in ('v1', 'v2'):
        (index.parent / f'demo.vectors-{version}.json').write_text(json.dumps(payload))
    assert checks(diagnose(path, full=True), 'vectors')[0]['status'] == 'ok'
    payload['records'][chunks[0]['id']]['vector'] = [1.0]
    (index.parent / 'demo.vectors-v2.json').write_text(json.dumps(payload))
    assert checks(diagnose(path, full=True), 'vectors')[0]['status'] == 'error'


def test_corrupt_relationship_metadata_reports_error(prepared):
    path, _, _, links = prepared
    links.write_text(json.dumps({'evidence_graph': {}, 'index_sources': {'demo': []}}))
    result = diagnose(path, full=True)
    assert checks(result, 'relationships')[0]['status'] == 'error'
