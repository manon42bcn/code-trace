"""Sessions reuse a bounded source snapshot and reject stale/expired/corrupt state."""

import json
import os
from pathlib import Path

import pytest

from coderag import agent_query, query_sessions, semantic_config
from coderag.query_pagination import CursorError, decode_cursor


@pytest.fixture
def search(tmp_path):
    index = tmp_path / 'index.json'
    links = tmp_path / 'links.json'
    config = tmp_path / 'config.json'
    chunks = [
        {
            'id': str(n),
            'path': f'api/{n}.py',
            'symbol': 'order_id',
            'content': f'order_id = {n}',
            'language': 'python',
            'start_line': n + 1,
            'end_line': n + 1,
        }
        for n in range(6)
    ]
    index.write_text(json.dumps({'chunks': chunks}))
    nodes = [{'id': f'node:{n}', 'chunk_id': str(n), 'path': f'api/{n}.py'} for n in range(6)]
    links.write_text(
        json.dumps(
            {
                'evidence_graph': {
                    'nodes': nodes,
                    'edges': [
                        {'source': 'node:0', 'target': 'node:5', 'type': 'calls'},
                    ],
                }
            }
        )
    )
    config.write_text(
        json.dumps({'context': {'max_chunks': 3}, 'generation': {'provider': 'invalid-never-used'}})
    )
    flags = [
        'order_id',
        '--index',
        str(index),
        '--relationships',
        str(links),
        '--config',
        str(config),
        '--limit',
        '4',
    ]

    def run(*extra):
        parser = agent_query.QueryParser()
        agent_query.configure_parser(parser)
        return agent_query.run(parser.parse_args([*flags, *extra]))

    return run, index, links, config, tmp_path


def test_resume_never_reads_artifacts_or_loads_provider(search, monkeypatch):
    run, index, links, config, root = search
    first = run('--page-size', '1', '--directory', 'api')
    cursor = first['pagination']['next_cursor']
    assert decode_cursor(cursor)['version'] == 2
    original = Path.read_text
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path in {index, links, config}:
            pytest.fail(f'Continuation reopened artifact: {path}')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guarded_open)

    def guarded_read(path, *args, **kwargs):
        if path in {index, links, config}:
            pytest.fail(f'Continuation reread full artifact: {path}')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', guarded_read)
    monkeypatch.setattr(
        semantic_config,
        'load_retrieval',
        lambda *_args, **_kwargs: pytest.fail('Continuation loaded retrieval/models'),
    )
    monkeypatch.setattr(
        agent_query,
        'plan_query',
        lambda *_args, **_kwargs: pytest.fail('Continuation regenerated query plan'),
    )
    second = run('--cursor', cursor, '--directory', 'api')
    assert second['pagination']['session']['reused']
    assert second['matches'][0]['chunk_id'] != first['matches'][0]['chunk_id']
    assert second['retrieval']['source_scope']['indexed_chunks'] == 6
    assert second['retrieval']['source_scope']['eligible_chunks'] == 6
    assert second == run('--cursor', cursor, '--directory', 'api')
    files = list((root / 'indexes/.query_sessions').glob('session-*.json'))
    assert len(files) == 1
    payload = json.loads(files[0].read_bytes())['payload']
    assert len(payload['index']['chunks']) == 4
    assert 'generation' not in payload
    assert 'invalid-never-used' not in files[0].read_text()
    if os.name != 'nt':
        assert files[0].stat().st_mode & 0o777 == 0o600


def test_session_and_stateless_evidence_are_equivalent(search):
    run, _, _, _, root = search
    cached = run('--page-size', '1', '--directory', 'api')
    legacy = run('--page-size', '1', '--directory', 'api', '--no-session')
    assert decode_cursor(legacy['pagination']['next_cursor'])['version'] == 1
    assert cached['matches'] == legacy['matches']
    assert cached['evidence'] == legacy['evidence']
    assert cached['context'] == legacy['context']
    # Neighbor metadata is retained even when the neighbor is outside the retrieval pool.
    assert cached['citations'] == legacy['citations']
    cached_report = run(
        '--page-size', '1', '--directory', 'api', '--report', str(root / 'cached.json')
    )
    legacy_report = run(
        '--page-size',
        '1',
        '--directory',
        'api',
        '--no-session',
        '--report',
        str(root / 'legacy.json'),
    )
    assert cached_report['matches'] == legacy_report['matches']
    assert (
        json.loads((root / 'cached.json').read_text())['context']
        == (json.loads((root / 'legacy.json').read_text())['context'])
    )
    second = run(
        '--cursor', cached['pagination']['next_cursor'], '--directory', 'api', '--max-chars', '5'
    )
    old_second = run(
        '--cursor', legacy['pagination']['next_cursor'], '--directory', 'api', '--max-chars', '5'
    )
    assert second['matches'] == old_second['matches']
    assert second['evidence'] == old_second['evidence']


@pytest.mark.parametrize('artifact', ['index', 'links', 'config'])
def test_artifact_changes_invalidate_sessions_even_with_restored_mtime(search, artifact):
    run, index, links, config, _ = search
    first = run('--page-size', '1')
    path = {'index': index, 'links': links, 'config': config}[artifact]
    before = path.stat()
    content = path.read_text()
    path.write_text(
        content.replace('order_id', 'other_id') if 'order_id' in content else content + ' '
    )
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(CursorError, match='artifacts changed') as exc:
        run('--cursor', first['pagination']['next_cursor'])
    assert exc.value.code == 'stale_cursor'


def test_expiry_is_fixed_and_not_extended_by_continuation(search, monkeypatch):
    run, _, _, _, _ = search
    now = [1000.0]
    monkeypatch.setattr(query_sessions.time, 'time', lambda: now[0])
    first = run('--page-size', '1', '--session-ttl', '10')
    now[0] = 1005.0
    second = run('--cursor', first['pagination']['next_cursor'])
    assert second['pagination']['session']['expires_at'] == 1010.0
    now[0] = 1011.0
    with pytest.raises(CursorError) as exc:
        run('--cursor', second['pagination']['next_cursor'])
    assert exc.value.code == 'session_expired'


@pytest.mark.parametrize('action', ['corrupt', 'delete', 'symlink'])
def test_missing_or_corrupt_sessions_never_fall_back_to_live_search(search, action):
    run, _, _, config, root = search
    first = run('--page-size', '1')
    token = first['pagination']['next_cursor']
    identifier = decode_cursor(token)['session']
    path = root / f'indexes/.query_sessions/session-{identifier}.json'
    if action == 'corrupt':
        path.write_text('{}')
    else:
        path.unlink()
        if action == 'symlink':
            path.symlink_to(config)
    with pytest.raises(CursorError) as exc:
        run('--cursor', token)
    assert exc.value.code == ('session_missing' if action == 'delete' else 'invalid_session')


def test_cache_cleanup_is_bounded_and_preserves_unknown_files(search, monkeypatch):
    run, _, _, _, root = search
    monkeypatch.setattr(query_sessions, 'MAX_SESSIONS', 2)
    first = run('--page-size', '1')
    folder = root / 'indexes/.query_sessions'
    (folder / 'notes.txt').write_text('keep')
    run('--page-size', '1')
    run('--page-size', '1')
    assert len(list(folder.glob('session-*.json'))) == 2
    assert (folder / 'notes.txt').read_text() == 'keep'
    with pytest.raises(CursorError) as exc:
        run('--cursor', first['pagination']['next_cursor'])
    assert exc.value.code == 'session_missing'


def test_custom_session_directory_and_report_metadata(search):
    run, _, _, _, root = search
    folder = root / 'cache with spaces'
    first = run('--page-size', '1', '--session-dir', str(folder))
    report = root / 'page-report.json'
    second = run(
        '--cursor',
        first['pagination']['next_cursor'],
        '--session-dir',
        str(folder),
        '--report',
        str(report),
    )
    assert json.loads(report.read_text())['metadata']['pagination'] == second['pagination']
    with pytest.raises(CursorError) as exc:
        run('--cursor', first['pagination']['next_cursor'])
    assert exc.value.code == 'session_missing'


def test_session_option_validation(search):
    run, _, _, _, _ = search
    for options in [
        ('--session-ttl', '0', '--page-size', '1'),
        ('--session-dir', 'cache'),
        ('--no-session', '--page-size', '1', '--session-ttl', '10'),
    ]:
        with pytest.raises(ValueError, match=r'(Session|session)'):
            run(*options)
    first = run('--page-size', '1')
    with pytest.raises(CursorError) as exc:
        run('--cursor', first['pagination']['next_cursor'], '--no-session')
    assert exc.value.code == 'invalid_cursor'


def test_semantic_continuation_skips_embeddings_and_vector_changes_invalidate(search, monkeypatch):
    from coderag import embedding_provider
    from coderag.embeddings import EmbeddingMetadata
    from coderag.vector_store import VectorStore

    _, index, links, config, root = search
    raw = json.loads(config.read_text())
    raw['retrieval'] = {'mode': 'semantic', 'semantic_enabled': True, 'embedding_model': 'test'}
    config.write_text(json.dumps(raw))
    metadata = EmbeddingMetadata('test', 2, 'v1')
    for version in ('v1', 'v2'):
        store = VectorStore(
            root / ('physical-v2.json' if version == 'v2' else 'index.vectors-v1.json')
        )
        store.upsert([{'chunk_id': str(n), 'vector': [1.0, 0.0]} for n in range(6)], metadata)
        store.save()
    (root / 'index.vectors-v2.json').symlink_to(root / 'physical-v2.json')
    counts = {'loads': 0, 'embeddings': 0}

    class Fake:
        def __init__(self, _model):
            counts['loads'] += 1
            self.metadata = metadata

        def embed_query(self, _query):
            counts['embeddings'] += 1
            return [1.0, 0.0]

    monkeypatch.setattr(embedding_provider, 'SentenceTransformerProvider', Fake)
    base = [
        'Where is order_id used?',
        '--index',
        str(index),
        '--relationships',
        str(links),
        '--config',
        str(config),
        '--limit',
        '4',
    ]

    def invoke(*flags):
        parser = agent_query.QueryParser()
        agent_query.configure_parser(parser)
        return agent_query.run(parser.parse_args([*base, *flags]))

    first = invoke('--page-size', '1')
    before = counts.copy()
    assert before['loads'] == 1
    assert before['embeddings'] > 0
    cursor = first['pagination']['next_cursor']
    second = invoke('--cursor', cursor)
    assert counts == before
    assert second['retrieval']['query_plan']['active_sources'] == ['semantic']
    path = root / 'index.vectors-v2.json'
    replacement = root / 'replacement.json'
    replacement.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(replacement)
    with pytest.raises(CursorError) as exc:
        invoke('--cursor', cursor)
    assert exc.value.code == 'stale_cursor'
    assert counts == before


def test_artifact_change_during_render_is_rejected_before_report(search, monkeypatch):
    run, index, _, _, root = search
    original = agent_query.answer

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        index.write_bytes(index.read_bytes() + b' ')
        return result

    monkeypatch.setattr(agent_query, 'answer', changing)
    report = root / 'stale-report.json'
    with pytest.raises(CursorError) as exc:
        run('--page-size', '1', '--report', str(report))
    assert exc.value.code == 'stale_cursor'
    assert not report.exists()


def test_expired_sessions_are_cleaned_when_a_new_search_starts(search, monkeypatch):
    run, _, _, _, root = search
    now = [1000.0]
    monkeypatch.setattr(query_sessions.time, 'time', lambda: now[0])
    first = run('--page-size', '1', '--session-ttl', '1')
    now[0] = 1002.0
    run('--page-size', '1')
    assert len(list((root / 'indexes/.query_sessions').glob('session-*.json'))) == 1
    with pytest.raises(CursorError) as exc:
        run('--cursor', first['pagination']['next_cursor'])
    assert exc.value.code == 'session_missing'


def test_oversized_session_is_explicit_and_can_be_disabled(search, monkeypatch):
    run, _, _, _, root = search
    monkeypatch.setattr(query_sessions, 'MAX_BYTES', 10)
    with pytest.raises(CursorError) as exc:
        run('--page-size', '1')
    assert exc.value.code == 'session_too_large'
    assert not (root / 'indexes/.query_sessions').exists()
    assert run('--page-size', '1', '--no-session')['matches']
