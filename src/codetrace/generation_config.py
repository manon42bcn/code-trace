"""Validated runtime configuration for optional generation."""

from __future__ import annotations

from dataclasses import dataclass


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
        if config.timeout_seconds <= 0 or config.max_tokens <= 0:
            raise ValueError('generation timeout and max_tokens must be positive')
        if config.provider not in {'none', 'anthropic', 'ollama', 'openai', 'azure_openai'}:
            raise ValueError('unsupported generation provider')
        if config.provider in {'openai', 'azure_openai'} and (
            not isinstance((value or {}).get('model'), str) or not config.model.strip()
        ):
            raise ValueError('Set generation.model explicitly for OpenAI or Azure OpenAI')
        return config
