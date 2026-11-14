from coderag.generation import Claim, GenerationResult
from coderag.rag_pipeline import answer


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
