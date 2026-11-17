"""Construct optional generation providers from validated configuration."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from .anthropic_provider import AnthropicProvider
from .generation_config import GenerationConfig, GenerationSetupError, read_generation_dotenv
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider

_CHAT_PROVIDERS = {
    'openai': ('OPENAI_API_KEY', None),
    'azure_openai': ('AZURE_OPENAI_API_KEY', None),
    'openrouter': ('OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1'),
    'groq': ('GROQ_API_KEY', 'https://api.groq.com/openai/v1'),
}


def build_generation_provider(config: GenerationConfig):
    """Create the adapter selected by the generation settings.

    Disabled generation returns None, and Ollama uses its configuration
    directly. For hosted providers, environment variables take precedence over
    values in the working directory's optional .env file.
    """
    if config.provider == 'none':
        return None
    if config.provider == 'ollama':
        return OllamaProvider(
            model=config.model,
            base_url=config.base_url or 'http://localhost:11434',
            timeout=config.timeout_seconds,
            max_tokens=config.max_tokens,
        )
    if config.provider == 'mlx':
        if config.base_url or config.proxy_url:
            raise GenerationSetupError(
                'MLX uses a local model directory without an endpoint or proxy'
            )
        from .mlx_provider import MLXProvider

        return MLXProvider(model=config.model, max_tokens=config.max_tokens)
    settings = read_generation_dotenv()

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
    if config.provider in _CHAT_PROVIDERS:
        azure = config.provider == 'azure_openai'
        key_name, default_base_url = _CHAT_PROVIDERS[config.provider]
        api_key = os.getenv(key_name, settings.get(key_name))
        if not api_key or not api_key.strip():
            raise GenerationSetupError(f'Set {key_name} in the environment or .env')
        base_url = config.base_url or default_base_url
        if azure:
            base_url = base_url or os.getenv(
                'AZURE_OPENAI_ENDPOINT', settings.get('AZURE_OPENAI_ENDPOINT')
            )
            if not base_url:
                raise GenerationSetupError(
                    'Set CODETRACE_GENERATION_BASE_URL or AZURE_OPENAI_ENDPOINT'
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
                # The shared client appends its Chat Completions path to this API root.
                base_url = f'https://{parsed.netloc}/openai/v1/'
        return OpenAIProvider(config=config, api_key=api_key, base_url=base_url)
    raise ValueError(f'unsupported generation provider: {config.provider}')
