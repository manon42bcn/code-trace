"""Query checks source freshness and coherent artifacts without rebuilding or breaking sessions."""

import json
import os
from pathlib import Path

import pytest

from coderag import agent_query, preparation, semantic_config
from coderag.core import index_repository
from coderag.evidence_graph import build_evidence_graph
from coderag.preparation import ReadinessError
from coderag.repo_links import build_repository_links, save_links


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / 'repo'
    source.mkdir()
    (source / 'api.py').write_text('def store_order():\n    return {"order_id": 1}\n')
    (source / 'other.py').write_text('def read_order():\n    return "order_id"\n')
    config = tmp_path / 'config.json'
    raw = {
        'repositories': {'demo': {'path': 'repo'}},
        'relationships': {},
        'generation': {'provider': 'must-not-probe'},
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
    config.write_text(json.dumps(raw))
    index = tmp_path / 'indexes/demo.chunks.json'
    links = tmp_path / 'indexes/demo.relationships.json'

    def rebuild():
        index_repository(source, index, raw, incremental=True)
        report = build_repository_links(raw, config, 'demo')
        report['evidence_graph'] = build_evidence_graph(
            {'demo': json.loads(index.read_text())}, report
        )
        save_links(links, report)

    rebuild()

    def run(*flags):
        parser = agent_query.QueryParser()
        agent_query.configure_parser(parser)
        return agent_query.run(
            parser.parse_args(
                [
                    'order_id',
                    '--config',
                    str(config),
                    '--default-repo',
                    'demo',
                    '--retrieval-mode',
                    'lexical',
                    *flags,
                ]
            )
        )

    return run, source, index, links, config, raw, rebuild


def test_current_queries_expose_assessment_without_mutation(prepared, tmp_path):
    run, _, index, links, _, _, _ = prepared
    before = index.read_bytes(), links.read_bytes()
    report = tmp_path / 'report.json'
    data = run('--report', str(report))
    assert data['readiness']['status'] == 'ok'
    assert data['readiness']['source']['status'] == 'current'
    assert data['readiness']['source']['verification'] == 'metadata'
    assert json.loads(report.read_text())['metadata']['readiness'] == data['readiness']
    assert before == (index.read_bytes(), links.read_bytes())
    assert run('--require-fresh')['readiness']['source']['verification'] == 'sha256'


@pytest.mark.parametrize('change', ['edit', 'add', 'delete', 'settings'])
def test_stale_source_warns_by_default_and_strict_blocks(prepared, change):
    run, source, _, _, config, raw, _ = prepared
    if change == 'edit':
        path = source / 'api.py'
        before = path.stat()
        path.write_text(path.read_text().replace('1', '2'))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif change == 'add':
        (source / 'added.py').write_text('')
    elif change == 'delete':
        (source / 'other.py').unlink()
    else:
        raw['indexing']['chunking']['max_tokens'] = 200
        config.write_text(json.dumps(raw))
    data = run()
    assert data['status'] == 'ok'
    assert data['readiness']['status'] == 'warning'
    assert data['readiness']['source']['status'] == 'stale'
    assert '--incremental' in data['readiness']['remedy']
    with pytest.raises(ReadinessError) as exc:
        run('--require-fresh')
    assert exc.value.code == 'source_not_fresh'
    assert run('--readiness', 'off')['readiness']['status'] == 'skipped'


def test_old_metadata_is_unknown_not_false_current(prepared):
    run, _, index, links, _, _, _ = prepared
    data = json.loads(index.read_text())
    data.pop('source_manifest')
    index.write_text(json.dumps(data))
    old_links = json.loads(links.read_text())
    old_links.pop('preparation_signature')
    old_links['index_sources']['demo'].pop('file_stamp')
    links.write_text(json.dumps(old_links))
    result = run()
    assert result['readiness']['status'] == 'warning'
    assert result['readiness']['source']['status'] == 'unknown'
    with pytest.raises(ReadinessError):
        run('--require-fresh')


def test_inconsistent_relationships_block_before_loading_models(prepared, monkeypatch):
    run, _, _, links, _, _, _ = prepared
    data = json.loads(links.read_text())
    data['index_sources']['demo']['created_at'] = 'old'
    links.write_text(json.dumps(data))
    monkeypatch.setattr(
        semantic_config,
        'load_retrieval',
        lambda *_args, **_kwargs: pytest.fail('Must check provenance before models'),
    )
    with pytest.raises(ReadinessError) as exc:
        run()
    assert exc.value.code == 'preparation_inconsistent'
    assert exc.value.readiness['status'] == 'error'


def test_link_configuration_changes_require_relinking(prepared):
    run, _, _, _, config, raw, _ = prepared
    raw['relationships']['demo'] = {
        'behave_scopes': [{'features': 'web/features', 'steps': ['steps']}]
    }
    config.write_text(json.dumps(raw))
    with pytest.raises(ReadinessError, match='inconsistent'):
        run()


def test_quick_sessions_refresh_source_checks_after_ttl_without_reading_artifacts(
    prepared, monkeypatch
):
    run, source, index, links, config, _, _ = prepared
    clock = [1000.0]
    monkeypatch.setattr(preparation.time, 'time', lambda: clock[0])
    first = run('--page-size', '1')
    cursor = first['pagination']['next_cursor']
    (source / 'api.py').write_text('def store_order():\n    return {"order_id": 2}\n')
    original = Path.open

    def guard(path, *args, **kwargs):
        if path in {index, links, config}:
            pytest.fail('Cached readiness reopened a full preparation artifact')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guard)
    warm = run('--cursor', cursor)
    assert warm['readiness']['source']['reused']
    assert warm['readiness']['source']['status'] == 'current'
    clock[0] = 1031.0
    updated = run('--cursor', cursor)
    assert updated['readiness']['source']['status'] == 'stale'
    assert updated['readiness']['source']['checked_at'] == 1031.0
    clock[0] = 1032.0
    again = run('--cursor', cursor)
    assert again['readiness']['source']['reused']
    assert again['readiness']['source']['checked_at'] == 1031.0


def test_full_session_checks_are_not_cached(prepared):
    run, source, _, _, _, _, _ = prepared
    first = run('--page-size', '1', '--require-fresh')
    cursor = first['pagination']['next_cursor']
    (source / 'api.py').write_text('def store_order():\n    return {"order_id": 9}\n')
    with pytest.raises(ReadinessError) as exc:
        run('--cursor', cursor, '--require-fresh')
    assert exc.value.code == 'source_not_fresh'


def test_direct_paths_without_configuration_do_not_invent_signature_mismatches(prepared):
    _, _, index, links, _, _, _ = prepared
    parser = agent_query.QueryParser()
    agent_query.configure_parser(parser)
    result = agent_query.run(
        parser.parse_args(
            [
                'order_id',
                '--index',
                str(index),
                '--relationships',
                str(links),
            ]
        )
    )
    assert result['status'] == 'ok'
    assert result['readiness']['status'] == 'warning'


@pytest.mark.parametrize('problem', ['identifiers', 'dimensions'])
def test_bad_vectors_fail_before_provider_creation(prepared, monkeypatch, problem):
    _, _, index, _, config, raw, _ = prepared
    from coderag import embedding_provider
    from coderag.embeddings import EmbeddingMetadata
    from coderag.vector_store import VectorStore

    raw['retrieval'] = {'semantic_enabled': True, 'embedding_model': 'test'}
    chunks = json.loads(index.read_text())
    for version in ('v1', 'v2'):
        store = VectorStore(index.with_name(f'demo.vectors-{version}.json'))
        store.upsert(
            [{'chunk_id': chunk['id'], 'vector': [1.0, 0.0]} for chunk in chunks['chunks']],
            EmbeddingMetadata('test', 2, version),
        )
        if problem == 'identifiers':
            store.records.pop(next(iter(store.records)))
        else:
            next(iter(store.records.values()))['vector'] = [1.0]
        store.save()
    monkeypatch.setattr(
        embedding_provider,
        'SentenceTransformerProvider',
        lambda *_args: pytest.fail('Invalid vectors must fail before loading the model'),
    )
    with pytest.raises(preparation.VectorPreparationError):
        semantic_config.load_retrieval(raw, config, index, index=chunks)


def test_dependency_replacement_invalidates_relationships(prepared):
    run, source, index, _, config, raw, rebuild = prepared
    raw['repositories']['shared'] = {'path': 'repo'}
    raw['relationships']['demo'] = {'dependencies': ['shared']}
    dependency = index.with_name('shared.chunks.json')
    index_repository(source, dependency, raw)
    config.write_text(json.dumps(raw))
    rebuild()
    assert run()['readiness']['status'] == 'ok'
    dependency.write_text(dependency.read_text() + '\n')
    with pytest.raises(ReadinessError) as exc:
        run()
    assert 'dependency index changed' in str(exc.value.readiness['checks'][-1]['message'])
