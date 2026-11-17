"""Validated runtime configuration for optional generation."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


class GenerationSetupError(ValueError):
    """An actionable generation setup error safe to show to users."""


@dataclass(frozen=True)
class GenerationConfig:
    provider: str = 'none'
    model: str = 'claude-opus-5-5'
    base_url: str | None = None
    proxy_url: str | None = None
    timeout_seconds: float = 120.0
    max_tokens: int = 4096
    effort: str = 'medium'

    @classmethod
    def from_mapping(cls, value: dict | None = None):
        config = cls(**(value or {}))
        if (
            not math.isfinite(config.timeout_seconds)
            or config.timeout_seconds <= 0
            or config.max_tokens <= 0
        ):
            raise ValueError('generation timeout and max_tokens must be positive')
        chat_providers = {'openai', 'azure_openai', 'openrouter', 'groq'}
        if config.provider not in {'none', 'anthropic', 'ollama', 'mlx'} | chat_providers:
            raise ValueError('unsupported generation provider')
        if config.provider in chat_providers | {'mlx'} and (
            not isinstance((value or {}).get('model'), str) or not config.model.strip()
        ):
            raise ValueError(f'Set generation.model explicitly for {config.provider}')
        return config


def read_generation_dotenv():
    """Read settings from the working directory without changing the process environment."""
    path = Path('.env')
    if not path.is_file():
        return {}
    try:
        return dotenv_values(path, interpolate=False)
    except (OSError, UnicodeError) as exc:
        raise GenerationSetupError('Cannot read .env as UTF-8') from exc


def generation_environment():
    """Read generation settings with exported values taking precedence over .env."""
    dotenv = read_generation_dotenv()
    settings = {}
    for field, convert in (
        ('provider', str),
        ('model', str),
        ('base_url', str),
        ('proxy_url', str),
        ('timeout_seconds', float),
        ('max_tokens', int),
        ('effort', str),
    ):
        name = f'CODETRACE_GENERATION_{field.upper()}'
        value = os.getenv(name, dotenv.get(name))
        if value is None or not value.strip():
            continue
        try:
            settings[field] = convert(value.strip())
        except ValueError as exc:
            raise GenerationSetupError(f'Invalid value for {name}') from exc
    return settings


def load_generation_config():
    """Load and validate runtime settings independently of the repository configuration."""
    settings = generation_environment()
    if settings.get('provider', 'none') != 'none' and 'model' not in settings:
        raise GenerationSetupError('Set CODETRACE_GENERATION_MODEL for the selected provider')
    return GenerationConfig.from_mapping(settings)
