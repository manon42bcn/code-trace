import pytest

from coderag.embeddings import EmbeddingMetadata
from coderag.vector_store import VectorStore


def metadata(dimensions=2):
    return EmbeddingMetadata('test-model', dimensions, 'config-1')


def test_vector_store_persists_and_searches(tmp_path):
    path = tmp_path / 'vectors.json'
    store = VectorStore(path)
    store.upsert(
        [
            {'chunk_id': 'a', 'vector': [1, 0], 'language': 'python'},
            {'chunk_id': 'b', 'vector': [0, 1], 'language': 'text'},
        ],
        metadata(),
    )
    store.save()
    loaded = VectorStore(path)
    assert loaded.search([1, 0], top_k=1)[0]['chunk_id'] == 'a'
    assert loaded.search([1, 0], filters={'language': 'text'})[0]['chunk_id'] == 'b'


def test_vector_store_rejects_incompatible_metadata(tmp_path):
    store = VectorStore(tmp_path / 'vectors.json')
    store.upsert([{'chunk_id': 'a', 'vector': [1, 0]}], metadata())
    with pytest.raises(ValueError, match='incompatible'):
        store.upsert(
            [{'chunk_id': 'b', 'vector': [1, 0]}], EmbeddingMetadata('other', 2, 'config-1')
        )
