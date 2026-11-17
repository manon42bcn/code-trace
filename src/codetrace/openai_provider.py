"""Generation through OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import json

from .generation import GenerationResult
from .generation_config import GenerationSetupError
from .structured_generation import parse_generation_json


class OpenAIRequestError(OSError):
    """A provider failure with a safe message and an optional HTTP status."""

    def __init__(self, provider, status_code):
        self.status_code = status_code
        detail = f'HTTP {status_code}' if status_code is not None else 'connection failed'
        super().__init__(f'{provider} request failed ({detail})')


class OpenAIProvider:
    """Adapt OpenAI-compatible services to the generation interface.

    The factory supplies credentials and the endpoint. The configured model
    identifies a model or, for Azure OpenAI, a deployment.
    """

    def __init__(self, *, config, api_key, base_url):
        try:
            import openai
        except ImportError as exc:
            raise GenerationSetupError('Install the OpenAI SDK with: uv sync --extra llm') from exc

        self.provider = config.provider
        self.model = config.model
        self.max_tokens = config.max_tokens
        self._api_error = openai.APIError
        self._timeout_error = openai.APITimeoutError
        options = {'api_key': api_key, 'timeout': config.timeout_seconds}
        if base_url:
            options['base_url'] = base_url
        if config.proxy_url:
            options['http_client'] = openai.DefaultHttpxClient(proxy=config.proxy_url)
        self._client = openai.OpenAI(**options)

    def generate(self, prompt: str, *, metadata=None) -> GenerationResult:  # noqa: ARG002 - Provider interface
        """Request a JSON object and convert it to a provider-independent result.

        Preserve model refusals as results so callers can handle them explicitly.
        Translate request failures into errors with a short message and reject
        completions that reached the output token limit.
        """
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                response_format={'type': 'json_object'},
                max_completion_tokens=self.max_tokens,
            )
        except self._timeout_error as exc:
            raise TimeoutError(f'{self.provider} request timed out') from exc
        except self._api_error as exc:
            raise OpenAIRequestError(self.provider, getattr(exc, 'status_code', None)) from exc
        if not response.choices:
            raise ValueError(f'{self.provider} returned no choices')
        choice = response.choices[0]
        message = choice.message
        if message.refusal or choice.finish_reason == 'content_filter':
            return GenerationResult(
                answer=message.refusal or '',
                provider=self.provider,
                model=self.model,
                refusal=True,
            )
        if choice.finish_reason == 'length':
            raise ValueError(f'{self.provider} response exceeded generation.max_tokens')
        try:
            return parse_generation_json(
                message.content or '', provider=self.provider, model=self.model
            )
        except (AttributeError, IndexError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(
                f'{self.provider} returned invalid structured generation JSON'
            ) from exc
