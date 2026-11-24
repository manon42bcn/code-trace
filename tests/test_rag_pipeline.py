from codetrace.generation import Claim, GenerationResult
from codetrace.rag_pipeline import answer


class FakeProvider:
    def generate(self, _prompt, *, metadata=None):  # noqa: ARG002 - Provider protocol keyword
        return GenerationResult(
            'answer',
            'fake',
            'model',
            claims=[Claim('fact', 'static_candidate', ['a'])],
            citations=[{'chunk_id': 'a'}],
        )


def data():
    return {'chunks': [{'id': 'a', 'path': 'a.py', 'content': 'evidence'}]}, {
        'nodes': [],
        'edges': [],
    }


def test_rag_pipeline_without_provider_returns_context():
    index, graph = data()
    result = answer(
        'What?', index=index, graph=graph, retrieval_results=[{'chunk_id': 'a', 'score': 1.0}]
    )
    assert result['generated'] is False
    assert result['answer'] is None
    assert 'Evidence:' in result['prompt']


def test_rag_pipeline_generates_and_validates_answer():
    index, graph = data()
    result = answer(
        'What?',
        index=index,
        graph=graph,
        retrieval_results=[{'chunk_id': 'a', 'score': 1.0}],
        generation_provider=FakeProvider(),
        allow_remote=True,
    )
    assert result['generated'] is True
    assert result['answer'].answer == 'answer'


def test_weak_semantic_matches_cannot_produce_an_unrelated_answer():
    class Embeddings:
        minimum_similarity = 0.1

        def embed_query(self, _query):
            return [1.0]

    class Store:
        def search(self, _vector, **_options):
            return [{'chunk_id': 'auth', 'score': 0.04}]

    class Model:
        provider = 'ollama'
        model = 'fixture'

        def generate(self, *_args, **_kwargs):
            raise AssertionError('The model should not receive unrelated evidence')

    index = {
        'chunks': [
            {'id': 'auth', 'path': 'auth.py', 'content': 'def login(): pass'},
        ]
    }
    result = answer(
        '¿Cómo envío datos al servicio de reportes?',
        index=index,
        graph={},
        generation_provider=Model(),
        prefer_direct=True,
        semantic_store=Store(),
        embedding_provider=Embeddings(),
    )

    assert result['answer_mode'] == 'insufficient_evidence'
    assert result['answer'].refusal
    assert result['context']['items'] == []
