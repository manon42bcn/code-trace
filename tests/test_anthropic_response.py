from types import SimpleNamespace

from coderag.anthropic_provider import AnthropicProvider


def test_anthropic_response_maps_refusal():
    provider = object.__new__(AnthropicProvider)
    provider.model = 'test-model'
    provider.max_tokens = 10
    provider.effort = 'low'
    provider._client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(
                content=[SimpleNamespace(type='text', text='declined')], stop_reason='refusal'
            )
        )
    )
    result = provider.generate('prompt')
    assert result.refusal is True
    assert result.answer == 'declined'
