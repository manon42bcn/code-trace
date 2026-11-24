"""Explicit registration and setup for supported generation adapters."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Literal
from urllib.parse import urlsplit

from ...generation import GenerationProvider
from ...generation_config import GenerationConfig, GenerationSetupError, read_generation_dotenv
from .anthropic import AnthropicProvider
from .mlx import MLXProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider


@dataclass(frozen=True)
class GenerationRegistration:
    create: Callable[[GenerationConfig], GenerationProvider]
    requires_model: bool = False
    execution: Literal['remote', 'local', 'loopback'] = 'remote'
    reuse_in_chat: bool = False


def _ollama(config):
    return OllamaProvider(
        model=config.model,
        base_url=config.base_url or 'http://localhost:11434',
        timeout=config.timeout_seconds,
        max_tokens=config.max_tokens,
    )


def _mlx(config):
    if config.base_url or config.proxy_url:
        raise GenerationSetupError('MLX uses a local model directory without an endpoint or proxy')
    return MLXProvider(model=config.model, max_tokens=config.max_tokens)


def _anthropic(config):
    settings = read_generation_dotenv()
    return AnthropicProvider(
        model=config.model,
        api_key=os.getenv('ANTHROPIC_API_KEY', settings.get('ANTHROPIC_API_KEY')) or None,
        auth_token=os.getenv('ANTHROPIC_AUTH_TOKEN', settings.get('ANTHROPIC_AUTH_TOKEN')) or None,
        base_url=config.base_url,
        proxy_url=config.proxy_url,
        timeout=config.timeout_seconds,
        max_tokens=config.max_tokens,
        effort=config.effort,
    )


def _openai_compatible(config, *, key_name, default_url=None, azure=False):
    settings = read_generation_dotenv()
    api_key = os.getenv(key_name, settings.get(key_name))
    if not api_key or not api_key.strip():
        raise GenerationSetupError(f'Set {key_name} in the environment or .env')
    base_url = config.base_url or default_url
    if azure:
        base_url = base_url or os.getenv(
            'AZURE_OPENAI_ENDPOINT', settings.get('AZURE_OPENAI_ENDPOINT')
        )
        if not base_url:
            raise GenerationSetupError('Set CODETRACE_GENERATION_BASE_URL or AZURE_OPENAI_ENDPOINT')
    if base_url:
        parsed = urlsplit(base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Use an HTTPS generation endpoint without URL credentials')
        if azure:
            if parsed.path.rstrip('/') not in {'', '/openai/v1'} or parsed.query or parsed.fragment:
                raise ValueError('Use the Azure resource endpoint or its /openai/v1/ URL')
            # The shared client appends its Chat Completions path to this API root.
            base_url = f'https://{parsed.netloc}/openai/v1/'
    return OpenAIProvider(config=config, api_key=api_key, base_url=base_url)


GENERATION_PROVIDERS = {
    'ollama': GenerationRegistration(_ollama, execution='loopback'),
    'mlx': GenerationRegistration(_mlx, requires_model=True, execution='local', reuse_in_chat=True),
    'anthropic': GenerationRegistration(_anthropic),
    'openai': GenerationRegistration(
        partial(_openai_compatible, key_name='OPENAI_API_KEY'), requires_model=True
    ),
    'azure_openai': GenerationRegistration(
        partial(_openai_compatible, key_name='AZURE_OPENAI_API_KEY', azure=True),
        requires_model=True,
    ),
    'openrouter': GenerationRegistration(
        partial(
            _openai_compatible,
            key_name='OPENROUTER_API_KEY',
            default_url='https://openrouter.ai/api/v1',
        ),
        requires_model=True,
    ),
    'groq': GenerationRegistration(
        partial(
            _openai_compatible,
            key_name='GROQ_API_KEY',
            default_url='https://api.groq.com/openai/v1',
        ),
        requires_model=True,
    ),
}


def build_generation_provider(config: GenerationConfig) -> GenerationProvider | None:
    if config.provider == 'none':
        return None
    entry = GENERATION_PROVIDERS.get(config.provider)
    if entry is None:
        raise ValueError(f'unsupported generation provider: {config.provider}')
    return entry.create(config)
