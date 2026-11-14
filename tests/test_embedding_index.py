from coderag.embedding_index import update_embedding_store
from coderag.embeddings import EmbeddingMetadata
from coderag.vector_store import VectorStore


class FakeProvider:
    metadata = EmbeddingMetadata('fake', 2, 'test')

    def __init__(self):
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(texts)
        return [[float(len(text)), 1.0] for text in texts]


def test_incremental_embedding_update_reuses_and_deletes(tmp_path):
    provider = FakeProvider()
    store = VectorStore(tmp_path / 'vectors.json')
    index = {
        'chunks': [
            {'id': 'a', 'path': 'a.py', 'language': 'python', 'content': 'one', 'sha256': 'a'},
            {'id': 'b', 'path': 'b.py', 'language': 'python', 'content': 'two', 'sha256': 'b'},
        ]
    }
    first = update_embedding_store(index, 'demo', provider, store)
    assert first == {'embedded': 2, 'reused': 0, 'deleted': 0}
    second = update_embedding_store({'chunks': [index['chunks'][0]]}, 'demo', provider, store)
    assert second == {'embedded': 0, 'reused': 1, 'deleted': 1}
    assert list(store.records) == ['a']
    assert len(provider.calls) == 1
