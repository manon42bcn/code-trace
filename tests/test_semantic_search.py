from coderag.embeddings import EmbeddingMetadata
from coderag.semantic_search import search_vectors
from coderag.vector_store import VectorStore


class FakeProvider:
    metadata = EmbeddingMetadata('fake', 2, 'test')

    def embed_query(self, query):
        return [1.0, 0.0] if 'order' in query else [0.0, 1.0]


def test_semantic_search_returns_normalized_results(tmp_path):
    store = VectorStore(tmp_path / 'vectors.json')
    store.upsert(
        [
            {
                'chunk_id': 'order',
                'vector': [1, 0],
                'path': 'orders.py',
                'language': 'python',
                'symbol': 'save_order',
            },
            {
                'chunk_id': 'user',
                'vector': [0, 1],
                'path': 'users.py',
                'language': 'python',
                'symbol': 'save_user',
            },
        ],
        FakeProvider.metadata,
    )
    results = search_vectors(store, FakeProvider(), 'find order', top_k=1)
    assert results[0]['chunk_id'] == 'order'
    assert results[0]['source'] == 'semantic'
    assert results[0]['symbol'] == 'save_order'
