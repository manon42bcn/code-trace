from coderag.generation_config import GenerationConfig
from coderag.generation_factory import build_generation_provider


def test_none_provider_keeps_offline_mode():
    assert build_generation_provider(GenerationConfig()) is None


def test_anthropic_provider_can_be_constructed_with_runtime_settings(monkeypatch):
    class FakeAnthropic:
        class DefaultHttpxClient:
            def __init__(self, proxy):
                self.proxy = proxy

        def __init__(self, **kwargs):
            self.kwargs = kwargs

    import sys

    module = type(
        'M',
        (),
        {'Anthropic': FakeAnthropic, 'DefaultHttpxClient': FakeAnthropic.DefaultHttpxClient},
    )
    monkeypatch.setitem(sys.modules, 'anthropic', module)
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'runtime-token')
    provider = build_generation_provider(
        GenerationConfig(provider='anthropic', base_url='https://gateway', proxy_url='http://proxy')
    )
    assert provider.model == 'claude-opus-5-5'
    assert provider._client.kwargs['auth_token'] == 'runtime-token'
    assert provider._client.kwargs['base_url'] == 'https://gateway'
