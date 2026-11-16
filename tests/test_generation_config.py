import pytest

from coderag.generation_config import GenerationConfig


def test_generation_config_defaults_to_offline():
    assert GenerationConfig.from_mapping().provider == 'none'


def test_generation_config_validates_provider_and_limits():
    with pytest.raises(ValueError, match='unsupported generation provider'):
        GenerationConfig.from_mapping({'provider': 'unknown'})
    with pytest.raises(ValueError, match='generation timeout and max_tokens must be positive'):
        GenerationConfig.from_mapping({'max_tokens': 0})
