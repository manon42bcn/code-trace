import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from codetrace.generation_config import GenerationConfig
from codetrace.generation_factory import build_generation_provider


class ApiError(Exception):
    status_code = 429


class ApiTimeoutError(ApiError):
    pass


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env').touch()
    for name in ('OPENAI_API_KEY', 'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT'):
        monkeypatch.delenv(name, raising=False)
    client = Mock()
    module = SimpleNamespace(
        OpenAI=Mock(return_value=client),
        DefaultHttpxClient=Mock(),
        APIError=ApiError,
        APITimeoutError=ApiTimeoutError,
    )
    monkeypatch.setitem(sys.modules, 'openai', module)
    return module, client.chat.completions.create


@pytest.mark.parametrize(
    ('provider_name', 'base_url'),
    [('openai', None), ('azure_openai', 'https://example.openai.azure.com/openai/v1/')],
)
def test_generation_uses_the_selected_service(tmp_path, sdk, provider_name, base_url):
    module, create = sdk
    (tmp_path / '.env').write_text(
        'OPENAI_API_KEY=openai-test-key\n'
        'AZURE_OPENAI_API_KEY=azure-test-key\n'
        'AZURE_OPENAI_ENDPOINT=https://example.openai.azure.com\n',
        encoding='utf-8',
    )
    config = GenerationConfig.from_mapping(
        {'provider': provider_name, 'model': 'configured-model', 'max_tokens': 200}
    )
    create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason='stop',
                message=SimpleNamespace(content='{"answer":"grounded"}', refusal=None),
            )
        ]
    )

    result = build_generation_provider(config).generate('JSON prompt')

    options = {'timeout': 120.0, 'api_key': 'openai-test-key'}
    if base_url:
        options.update(api_key='azure-test-key', base_url=base_url)
    module.OpenAI.assert_called_once_with(**options)
    create.assert_called_once_with(
        model='configured-model',
        messages=[{'role': 'user', 'content': 'JSON prompt'}],
        response_format={'type': 'json_object'},
        max_completion_tokens=200,
    )
    assert (result.answer, result.provider, result.model) == (
        'grounded',
        provider_name,
        'configured-model',
    )


def test_request_error_preserves_status_without_leaking_provider_body(monkeypatch, sdk):
    _module, create = sdk
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    config = GenerationConfig.from_mapping({'provider': 'openai', 'model': 'configured-model'})
    create.side_effect = ApiError('sensitive provider response')

    with pytest.raises(OSError, match=r'^openai request failed \(HTTP 429\)$') as error:
        build_generation_provider(config).generate('JSON prompt')

    assert error.value.status_code == 429


def test_azure_requires_its_own_key(monkeypatch, sdk):
    module, _create = sdk
    monkeypatch.setenv('OPENAI_API_KEY', 'openai-test-key')
    monkeypatch.delenv('AZURE_OPENAI_API_KEY', raising=False)
    config = GenerationConfig.from_mapping({'provider': 'azure_openai', 'model': 'deployment'})

    with pytest.raises(ValueError, match='AZURE_OPENAI_API_KEY'):
        build_generation_provider(config)

    module.OpenAI.assert_not_called()


def test_env_file_is_required_even_with_an_exported_key(monkeypatch, sdk, tmp_path):
    module, _create = sdk
    (tmp_path / '.env').unlink()
    monkeypatch.setenv('OPENAI_API_KEY', 'openai-test-key')
    config = GenerationConfig.from_mapping({'provider': 'openai', 'model': 'configured-model'})

    with pytest.raises(ValueError, match=r'Copy \.env\.example to \.env'):
        build_generation_provider(config)

    module.OpenAI.assert_not_called()
