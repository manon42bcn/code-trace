"""Construct optional generation providers from validated configuration."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .anthropic_provider import AnthropicProvider
from .generation_config import GenerationConfig, GenerationSetupError
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider


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
    dotenv_path = Path('.env')
    settings = {}
    if dotenv_path.is_file():
        try:
            settings = dotenv_values(dotenv_path, interpolate=False)
        except (OSError, UnicodeError) as exc:
            raise GenerationSetupError('Cannot read .env as UTF-8') from exc
    elif config.provider in {'openai', 'azure_openai'}:
        raise GenerationSetupError('Copy .env.example to .env in the working directory')

    if config.provider == 'anthropic':
        return AnthropicProvider(
            model=config.model,
            api_key=os.getenv('ANTHROPIC_API_KEY', settings.get('ANTHROPIC_API_KEY')) or None,
            auth_token=os.getenv('ANTHROPIC_AUTH_TOKEN', settings.get('ANTHROPIC_AUTH_TOKEN'))
            or None,
            base_url=config.base_url,
            proxy_url=config.proxy_url,
            timeout=config.timeout_seconds,
            max_tokens=config.max_tokens,
            effort=config.effort,
        )
    if config.provider in {'openai', 'azure_openai'}:
        azure = config.provider == 'azure_openai'
        key_name = 'AZURE_OPENAI_API_KEY' if azure else 'OPENAI_API_KEY'
        api_key = os.getenv(key_name, settings.get(key_name))
        if not api_key or not api_key.strip():
            raise GenerationSetupError(f'Set {key_name} in .env')
        base_url = config.base_url
        if azure:
            base_url = base_url or os.getenv(
                'AZURE_OPENAI_ENDPOINT', settings.get('AZURE_OPENAI_ENDPOINT')
            )
            if not base_url:
                raise GenerationSetupError(
                    'Set generation.base_url or AZURE_OPENAI_ENDPOINT in .env'
                )
        if base_url:
            parsed = urlsplit(base_url)
            if (
                parsed.scheme != 'https'
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError('Use an HTTPS generation endpoint without URL credentials')
            if azure:
                if (
                    parsed.path.rstrip('/') not in {'', '/openai/v1'}
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError('Use the Azure resource endpoint or its /openai/v1/ URL')
                base_url = f'https://{parsed.netloc}/openai/v1/'
        return OpenAIProvider(config=config, api_key=api_key, base_url=base_url)
    raise ValueError(f'unsupported generation provider: {config.provider}')
