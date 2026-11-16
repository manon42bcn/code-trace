"""Construct optional generation providers from validated configuration."""

from __future__ import annotations

import os

from .anthropic_provider import AnthropicProvider
from .generation_config import GenerationConfig
from .ollama_provider import OllamaProvider


def build_generation_provider(config: GenerationConfig):
    """Return a configured provider, or None for the offline default."""
    if config.provider == 'none':
        return None
    if config.provider == 'ollama':
        return OllamaProvider(
            model=config.model,
            base_url=config.base_url or 'http://localhost:11434',
            timeout=config.timeout_seconds,
            max_tokens=config.max_tokens,
        )
    if config.provider == 'anthropic':
        return AnthropicProvider(
            model=config.model,
            api_key=os.getenv('ANTHROPIC_API_KEY'),
            auth_token=os.getenv('ANTHROPIC_AUTH_TOKEN'),
            base_url=config.base_url,
            proxy_url=config.proxy_url,
            timeout=config.timeout_seconds,
            max_tokens=config.max_tokens,
            effort=config.effort,
        )
    raise ValueError(f'unsupported generation provider: {config.provider}')
