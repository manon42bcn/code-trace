import json

import pytest

from coderag.embeddings import EmbeddingMetadata
from coderag.prepare_embeddings import prepare
from coderag.semantic_config import load_retrieval, resolve_retrieval
from coderag.vector_store import VectorStore


class Provider:
    def __init__(self, model='fake'):
        self.metadata = EmbeddingMetadata(model, 2, 'v1')
        self.calls = []

    def embed_documents(self, texts):
        self.calls.extend(texts)
        return [[1.0, float(len(text))] for text in texts]

    def embed_query(self, text):
        return [1.0, float(len(text))]


@pytest.fixture
def config(tmp_path):
    (tmp_path / 'indexes').mkdir()
    raw = {
        'retrieval': {'semantic_enabled': True, 'embedding_model': 'fake'},
        'repositories': {name: {} for name in ('app', 'lib')},
    }
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(raw))
    for name in ('app', 'lib'):
        (tmp_path / f'indexes/{name}.chunks.json').write_text(
            json.dumps(
                {
                    'chunks': [
                        {
                            'id': name,
                            'path': f'{name}.py',
                            'content': 'order_id = 1',
                            'sha256': 'same',
                        }
                    ]
                }
            )
        )
        (tmp_path / f'indexes/{name}.relationships.json').write_text(
            json.dumps(
                {
                    'evidence_graph': {
                        'nodes': [
                            {'id': 'symbol', 'chunk_id': name},
                            {'id': 'key', 'kind': 'data_key', 'key': 'order_id'},
                        ],
                        'edges': [{'source': 'symbol', 'target': 'key', 'type': 'writes'}],
                    }
                }
            )
        )
    return path, raw


def test_prepare_and_query_share_per_repository_stores(config, monkeypatch):
    path, raw = config
    from coderag import embedding_provider

    monkeypatch.setattr(embedding_provider, 'SentenceTransformerProvider', Provider)
    for name in ('app', 'lib'):
        result = prepare(path, name, provider=Provider())
        assert result['stores']['v1']['embedded'] == 1
        assert result['stores']['v2']['embedded'] == 1
        index_path = path.parent / f'indexes/{name}.chunks.json'
        retrieval, stores, provider = load_retrieval(raw, path, index_path)
        assert retrieval.semantic_profile == 'two_stage'
        assert set(stores['v1'].records) == {name}
        assert set(stores['v2'].records) == {name}
        assert stores['v1'].search(provider.embed_query('order_id'))[0]['chunk_id'] == name


def test_incremental_graph_change_reembeds_only_enriched_store(config):
    path, _ = config
    prepare(path, 'app', provider=Provider())
    second = prepare(path, 'app', provider=Provider())
    assert all(item['reused'] == 1 for item in second['stores'].values())
    graph_path = path.parent / 'indexes/app.relationships.json'
    graph = json.loads(graph_path.read_text())
    graph['evidence_graph']['edges'][0]['type'] = 'reads'
    graph_path.write_text(json.dumps(graph))
    third = prepare(path, 'app', provider=Provider())
    assert third['stores']['v1']['embedded'] == 0
    assert third['stores']['v2']['embedded'] == 1


def test_empty_indexes_and_deleted_chunks_remain_queryable(config):
    path, raw = config
    prepare(path, 'app', provider=Provider())
    index = path.parent / 'indexes/app.chunks.json'
    index.write_text('{"chunks": []}')
    result = prepare(path, 'app', provider=Provider())
    assert result['stores']['v1']['deleted'] == 1
    _, paths, _ = resolve_retrieval(raw, path, index)
    assert VectorStore(paths['v1']).records == {}
    assert VectorStore(paths['v1']).metadata is not None


def test_model_change_rebuilds_existing_vectors(config):
    path, _ = config
    prepare(path, 'app', provider=Provider())
    result = prepare(path, 'app', provider=Provider('different'))
    assert all(item['embedded'] == 1 for item in result['stores'].values())


def test_missing_vectors_fail_before_model_loading(config):
    path, raw = config
    with pytest.raises(ValueError, match='run make indexes'):
        load_retrieval(raw, path, path.parent / 'indexes/app.chunks.json')


def test_per_repository_disable_and_explicit_paths(config):
    path, raw = config
    raw['repositories']['lib']['retrieval'] = {'semantic_enabled': False}
    assert resolve_retrieval(raw, path, path.parent / 'indexes/lib.chunks.json')[1] is None
    raw['repositories']['app']['retrieval'] = {
        'semantic_v1_store': 'a.json',
        'semantic_v2_store': 'b.json',
    }
    assert (
        resolve_retrieval(raw, path, path.parent / 'indexes/app.chunks.json')[1]['v1']
        == path.parent / 'a.json'
    )


def test_prepared_vectors_are_consumed_by_compact_query(config, monkeypatch, capsys):
    from coderag import agent_query, embedding_provider

    path, _raw = config
    prepare(path, 'app', provider=Provider())
    monkeypatch.setattr(embedding_provider, 'SentenceTransformerProvider', Provider)
    # A non-literal question exercises semantic retrieval, not an exact key match.
    agent_query.main(
        [
            'Where is the order identifier assigned?',
            '--index',
            str(path.parent / 'indexes/app.chunks.json'),
            '--relationships',
            str(path.parent / 'indexes/app.relationships.json'),
            '--config',
            str(path),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'ok'
    assert result['citations'][0]['chunk_id'] == 'app'
    assert result['answer'] is None


def test_default_profile_can_query_a_pair_of_stores(config, monkeypatch):
    from coderag import embedding_provider
    from coderag.search import search_hybrid

    path, raw = config
    prepare(path, 'app', provider=Provider())
    monkeypatch.setattr(embedding_provider, 'SentenceTransformerProvider', Provider)
    raw['retrieval']['semantic_profile'] = 'default'
    _, stores, provider = load_retrieval(raw, path, path.parent / 'indexes/app.chunks.json')
    index = json.loads((path.parent / 'indexes/app.chunks.json').read_text())
    results = search_hybrid(
        index,
        {},
        'Where is the order identifier assigned?',
        semantic_store=stores,
        provider=provider,
    )
    assert results[0]['chunk_id'] == 'app'
