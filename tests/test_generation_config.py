import pytest

from codetrace.generation_config import GenerationConfig, load_generation_config


def test_generation_config_defaults_to_offline():
    assert GenerationConfig.from_mapping().provider == 'none'


def test_generation_config_validates_provider_and_limits():
    with pytest.raises(ValueError, match='unsupported generation provider'):
        GenerationConfig.from_mapping({'provider': 'unknown'})
    with pytest.raises(ValueError, match='generation timeout and max_tokens must be positive'):
        GenerationConfig.from_mapping({'max_tokens': 0})


def test_environment_overrides_dotenv_and_never_uses_config_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('CODETRACE_GENERATION_BASE_URL', raising=False)
    monkeypatch.delenv('CODETRACE_GENERATION_MAX_TOKENS', raising=False)
    monkeypatch.setenv('CODETRACE_GENERATION_PROVIDER', 'openrouter')
    monkeypatch.setenv('CODETRACE_GENERATION_MODEL', 'configured-model')
    (tmp_path / '.env').write_text(
        'CODETRACE_GENERATION_MODEL=file-model\nCODETRACE_GENERATION_MAX_TOKENS=256\n'
    )
    (tmp_path / 'config.json').write_text(
        '{"generation":{"provider":"azure_openai","base_url":"https://old.example"}}'
    )

    config = load_generation_config()

    assert config.provider == 'openrouter'
    assert config.model == 'configured-model'
    assert config.max_tokens == 256
    assert config.base_url is None
