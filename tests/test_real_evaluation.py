"""Real-suite runner invariants use isolated indexed sources, never private repositories."""

import copy
import json
import subprocess
import sys

import pytest

from coderag.core import index_repository
from coderag.real_evaluation import compare_reports, load_suite, run_suite


@pytest.fixture
def suite(tmp_path):
    source = tmp_path / 'repo'
    source.mkdir()
    (source / 'api.py').write_text('def send_request():\n    return "HTTP POST"\n')
    (source / 'tools.json').write_text('{"tools": [{"name": "a"}, {"name": "b"}]}')
    raw = {
        'repositories': {'demo': {'path': 'repo'}, 'other': {'path': 'unused'}},
        'retrieval': {'semantic_enabled': True},
        'generation': {'provider': 'invalid-must-not-be-loaded'},
        'indexing': {
            'languages': ['python', 'json'],
            'chunking': {
                'strategy': 'structural',
                'max_tokens': 100,
                'overlap_tokens': 0,
                'preserve_symbols': True,
                'include_parent_context': True,
                'on_missing_parser': 'error',
            },
        },
    }
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(raw))
    index = tmp_path / 'indexes/demo.chunks.json'
    index_repository(source, index, raw)
    (index.parent / 'demo.relationships.json').write_text(
        '{"evidence_graph": {"nodes": [], "edges": []}}'
    )
    cases = [
        {
            'id': 'source',
            'kind': 'evidence',
            'question': 'Where is POST sent?',
            'query': 'send_request',
            'default_repo': 'demo',
            'expected': {
                'repository': 'demo',
                'sources': [
                    {'path': 'api.py', 'symbol': 'send_request', 'contains': ['HTTP POST']},
                ],
            },
        },
        {
            'id': 'absent',
            'kind': 'absent',
            'question': 'Any evidence?',
            'query': 'missing_sentinel',
            'default_repo': 'demo',
            'expected': {'repository': 'demo'},
        },
        {
            'id': 'count',
            'kind': 'inventory',
            'question': 'How many tools?',
            'query': 'tools',
            'default_repo': 'demo',
            'file': 'tools.json',
            'path': '$/tools',
            'unique_by': 'name',
            'expected': {'repository': 'demo', 'total': 2},
        },
        {
            'id': 'route',
            'kind': 'routing',
            'question': 'Both repos?',
            'query': 'demo and other',
            'default_repo': 'demo',
            'expected': {'error': 'ambiguous_repository'},
        },
    ]
    dataset = tmp_path / 'suite.json'
    dataset.write_text(json.dumps({'schema_version': 1, 'cases': cases}))
    return dataset, config


def test_suite_uses_existing_pipeline_without_models_or_source_writes(suite):
    dataset, config = suite
    before = config.read_bytes()
    report = run_suite(dataset, config)
    assert report['passed'] == report['cases'] == 4
    assert report['failed'] == 0
    assert report['generation_evaluated'] is False
    assert report['rows'][0]['context_source_coverage'] == 1
    assert report['rows'][0]['citations_valid']
    assert report['rows'][2]['total'] == 2
    assert report['artifacts']['demo']['index_sha256']
    assert report['rows'][0]['latency_seconds'] >= 0
    assert config.read_bytes() == before
    assert 'HTTP POST' not in json.dumps(report)


def test_missing_gold_labels_fail_without_false_perfect_recall(suite):
    dataset, config = suite
    data = json.loads(dataset.read_text())
    data['cases'][0]['expected']['sources'][0]['symbol'] = 'unknown_function'
    dataset.write_text(json.dumps(data))
    result = run_suite(dataset, config)
    assert result['failed'] == 1
    assert not result['rows'][0]['gold_sources_found']
    assert result['rows'][0]['context_source_coverage'] == 0
    assert result['rows'][0]['context_metrics']['coverage'] is None
    assert result['rows'][0]['coverage_status'] == 'gold_sources_missing'


def test_unavailable_artifact_does_not_silently_skip_case(suite):
    dataset, config = suite
    (config.parent / 'indexes/demo.chunks.json').unlink()
    result = run_suite(dataset, config)
    assert result['failed'] == 3
    assert result['cases'] == 4
    assert result['rows'][-1]['passed']


def test_comparison_and_validation(suite):
    dataset, config = suite
    current = run_suite(dataset, config)
    old = copy.deepcopy(current)
    old['rows'][0]['passed'] = False
    assert compare_reports(current, old)['improved'] == ['source']
    old['profile'] = 'configured'
    with pytest.raises(ValueError, match='same dataset'):
        compare_reports(current, old)
    with pytest.raises(ValueError, match='Unknown cases'):
        run_suite(dataset, config, selected=['unknown'])
    data = json.loads(dataset.read_text())
    data['cases'][0]['expected']['sources'] = []
    dataset.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='source labels'):
        load_suite(dataset)


def test_cli_report_exit_status_and_case_selection(suite, tmp_path):
    dataset, config = suite
    report = tmp_path / 'report.json'
    args = [
        sys.executable,
        '-m',
        'coderag',
        'evaluate-real',
        '--dataset',
        str(dataset),
        '--config',
        str(config),
        '--output',
        str(report),
    ]
    proc = subprocess.run(args, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(report.read_text())['passed'] == 4
    (config.parent / 'indexes/demo.chunks.json').unlink()
    proc = subprocess.run(args, capture_output=True, text=True)
    assert proc.returncode == 1
    assert json.loads(report.read_text())['failed'] == 3
    proc = subprocess.run([*args, '--case', 'route'], capture_output=True, text=True)
    assert proc.returncode == 0
    assert json.loads(report.read_text())['cases'] == 1


def test_profile_comparison_uses_same_cases_and_semantic_only_provider(suite, monkeypatch):
    from coderag import embedding_provider
    from coderag.embeddings import EmbeddingMetadata
    from coderag.real_evaluation import compare_profiles
    from coderag.vector_store import VectorStore

    dataset, config = suite
    raw = json.loads(config.read_text())
    raw['retrieval']['embedding_model'] = 'test'
    config.write_text(json.dumps(raw))
    index = json.loads((config.parent / 'indexes/demo.chunks.json').read_text())
    metadata = EmbeddingMetadata('test', 2, 'v1')
    for version in ('v1', 'v2'):
        store = VectorStore(config.parent / f'indexes/demo.vectors-{version}.json')
        store.upsert(
            [
                {
                    'chunk_id': chunk['id'],
                    'vector': [1.0, 0.0] if chunk['path'] == 'api.py' else [0.0, 1.0],
                }
                for chunk in index['chunks']
            ],
            metadata,
        )
        store.save()
    calls = []

    class Fake:
        def __init__(self, model):
            assert model == 'test'
            self.metadata = metadata

        def embed_query(self, query):
            calls.append(query)
            return [1.0, 0.0]

    monkeypatch.setattr(embedding_provider, 'SentenceTransformerProvider', Fake)
    report = compare_profiles(dataset, config, selected=['source'])
    assert report['passed'] == 1
    assert report['failed'] == 0
    assert report['comparable_source_snapshots']
    assert calls
    assert set(calls) == {'send_request'}
    assert report['runs']['semantic']['rows'][0]['query_plan']['active_sources'] == ['semantic']
    assert report['runs']['lexical']['rows'][0]['query_plan']['active_sources'] == [
        'lexical',
        'structural',
    ]
    assert (
        report['runs']['semantic']['rows'][0]['query']
        == report['runs']['lexical']['rows'][0]['query']
    )


def test_missing_semantic_stores_are_recorded_without_lexical_fallback(suite):
    from coderag.real_evaluation import compare_profiles

    dataset, config = suite
    report = compare_profiles(dataset, config, selected=['source'])
    assert report['runs']['lexical']['passed'] == 1
    assert report['runs']['semantic']['passed'] == 0
    assert 'Semantic vectors missing' in report['runs']['semantic']['rows'][0]['error']['message']
    assert report['comparable_source_snapshots']
    with pytest.raises(ValueError, match='retrieval-only'):
        compare_profiles(dataset, config)


def test_comparison_cli_persists_failed_profiles(suite, tmp_path):
    dataset, config = suite
    target = tmp_path / 'comparison.json'
    proc = subprocess.run(
        [
            sys.executable,
            '-m',
            'coderag',
            'evaluate-real',
            '--dataset',
            str(dataset),
            '--config',
            str(config),
            '--compare-profiles',
            '--case',
            'source',
            '--output',
            str(target),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads(target.read_text())
    assert report['profile'] == 'comparison'
    assert report['runs']['semantic']['failed'] == 1


def test_incomparable_comparison_is_not_success_even_with_zero_failed_cases(tmp_path, monkeypatch):
    from coderag import real_evaluation

    monkeypatch.setattr(
        real_evaluation,
        'compare_profiles',
        lambda *_args, **_kwargs: {
            'status': 'failed',
            'failed': 0,
            'passed': 1,
            'comparable_source_snapshots': False,
        },
    )
    with pytest.raises(SystemExit) as exc:
        real_evaluation.main(['--compare-profiles', '--output', str(tmp_path / 'report.json')])
    assert exc.value.code == 1
    assert not json.loads((tmp_path / 'report.json').read_text())['comparable_source_snapshots']
