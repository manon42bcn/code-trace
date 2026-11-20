import pytest

from codetrace.answering import answer_query
from codetrace.generation import Claim, GenerationResult


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


@pytest.mark.parametrize('retry_end', [None, 20])
def test_out_of_bounds_citation_retries_once(retry_end):
    context = {
        'items': [
            {
                'chunk': {'id': 'a'},
                'content': 'evidence',
                'citation': {'chunk_id': 'a', 'path': 'a.py', 'start_line': 3, 'end_line': 5},
            }
        ]
    }
    prompts = []

    class Provider(FakeProvider):
        def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            citation = {'chunk_id': 'a'}
            end_line = 20 if len(prompts) == 1 else retry_end
            if end_line is not None:
                citation['end_line'] = end_line
            return GenerationResult(
                'grounded answer',
                self.provider,
                self.model,
                claims=[Claim('claim', 'static_candidate', ['a'])],
                citations=[citation],
            )

    timings = {}
    if retry_end is None:
        result = answer_query(
            'What happens?', context, Provider(), allow_remote=True, timings=timings
        )
        assert result.citations == [{'chunk_id': 'a'}]
    else:
        with pytest.raises(ValueError, match='citation end_line is outside context'):
            answer_query('What happens?', context, Provider(), allow_remote=True, timings=timings)
    assert len(prompts) == 2
    assert '"citations":[{"chunk_id":"string"}]' in prompts[0]
    assert prompts[1].startswith(prompts[0])
    assert 'Omit path, start_line and end_line' in prompts[1]
    assert timings['generation_seconds'] > 0


def test_invented_chunk_id_retries_with_context_ids():
    class Provider(FakeProvider):
        def __init__(self):
            self.prompts = []

        def generate(self, prompt, **_kwargs):
            self.prompts.append(prompt)
            cited_id = 'chunk_1' if len(self.prompts) == 1 else 'a'
            return GenerationResult(
                'grounded answer',
                self.provider,
                self.model,
                claims=[Claim('claim', 'static_candidate', [cited_id])],
                citations=[{'chunk_id': cited_id}],
            )

    provider = Provider()
    context = {'items': [{'chunk': {'id': 'a'}, 'citation': {'chunk_id': 'a'}}]}
    result = answer_query('What happens?', context, provider, allow_remote=True)

    assert result.citations == [{'chunk_id': 'a'}]
    assert len(provider.prompts) == 2
    assert 'Allowed citation chunk IDs: ["a"]' in provider.prompts[0]
    assert 'Copy IDs verbatim' in provider.prompts[1]
