import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from codetrace.answering import answer_query
from codetrace.generation_config import GenerationConfig, GenerationSetupError
from codetrace.generation_factory import build_generation_provider
from codetrace.provider_check import check_provider


@pytest.fixture
def mlx_model(tmp_path, monkeypatch):
    (tmp_path / 'config.json').touch()
    tokenizer = Mock(chat_template='template')
    tokenizer.apply_chat_template.return_value = [1, 2, 3]
    model = object()
    sdk = SimpleNamespace(
        load=Mock(return_value=(model, tokenizer)),
        generate=Mock(return_value='{"answer":"ok"}'),
    )
    monkeypatch.setitem(sys.modules, 'mlx_lm', sdk)
    settings = {'provider': 'mlx', 'model': str(tmp_path), 'max_tokens': 200}
    return settings, sdk, model, tokenizer


def test_mlx_runs_grounded_answers_locally_and_reuses_loaded_model(mlx_model):
    settings, sdk, model, tokenizer = mlx_model
    provider = build_generation_provider(GenerationConfig.from_mapping(settings))
    sdk.load.assert_not_called()

    result = answer_query('question', {'items': []}, provider)
    provider.generate('another question')

    assert (result.provider, result.answer) == ('mlx', 'ok')
    sdk.load.assert_called_once_with(Path(settings['model']).resolve())
    tokenizer.apply_chat_template.assert_called_with(
        [{'role': 'user', 'content': 'another question'}], add_generation_prompt=True
    )
    sdk.generate.assert_called_with(
        model, tokenizer, prompt=[1, 2, 3], max_tokens=200, verbose=False
    )


def test_mlx_probe_requires_no_remote_consent(mlx_model):
    settings, sdk, model, tokenizer = mlx_model

    result = check_provider({'generation': settings})

    assert result['generation_verified']
    assert result['provider'] == 'mlx'
    sdk.generate.assert_called_once_with(
        model, tokenizer, prompt=[1, 2, 3], max_tokens=128, verbose=False
    )


def test_mlx_rejects_hub_ids_and_network_configuration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(GenerationSetupError, match='local MLX LM model directory'):
        build_generation_provider(GenerationConfig(provider='mlx', model='org/model'))

    with pytest.raises(GenerationSetupError, match='without an endpoint or proxy'):
        build_generation_provider(
            GenerationConfig(provider='mlx', model='model', base_url='https://example.test')
        )


def test_mlx_rejects_unstructured_output(mlx_model):
    settings, sdk, _, _ = mlx_model
    sdk.generate.return_value = 'not JSON'

    with pytest.raises(ValueError, match='invalid structured generation JSON'):
        build_generation_provider(GenerationConfig.from_mapping(settings)).generate('question')
