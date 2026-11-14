import pytest

from coderag.answering import answer_query
from coderag.generation import Claim, GenerationResult


class FakeProvider:
    provider = 'fake'
    model = 'test-model'

    def generate(self, prompt, *, metadata=None):  # noqa: ARG002 - Provider protocol keyword
        assert 'Evidence:' in prompt
        return GenerationResult(
            'grounded answer',
            self.provider,
            self.model,
            claims=[Claim('claim', 'static_candidate', ['a'])],
            citations=[{'chunk_id': 'a'}],
        )


def test_answer_query_builds_and_validates_grounded_result():
    context = {
        'items': [
            {
                'chunk': {'id': 'a'},
                'content': 'evidence',
                'citation': {'chunk_id': 'a', 'path': 'a.py', 'start_line': 1},
            }
        ]
    }
    result = answer_query('What happens?', context, FakeProvider(), allow_remote=True)
    assert result.answer == 'grounded answer'


def test_answer_query_rejects_invalid_provider_output():
    class BadProvider(FakeProvider):
        def generate(self, _prompt, *, metadata=None):  # noqa: ARG002 - Provider protocol keyword
            return {'answer': 'not structured'}

    with pytest.raises(TypeError):
        answer_query('What happens?', {'items': []}, BadProvider(), allow_remote=True)
