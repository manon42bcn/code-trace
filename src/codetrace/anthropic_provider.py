"""Optional Anthropic generation adapter with endpoint and proxy support."""

from __future__ import annotations

import json

from .generation import GenerationResult
from .structured_generation import parse_generation_json


class AnthropicProvider:
    provider = 'anthropic'

    def __init__(
        self,
        *,
        model='claude-opus-5-5',
        api_key=None,
        auth_token=None,
        base_url=None,
        proxy_url=None,
        timeout=120.0,
        max_tokens=4096,
        effort='medium',
    ):
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError('anthropic is required; install with: uv sync --extra llm') from exc
        client_args = {'timeout': timeout}
        if api_key:
            client_args['api_key'] = api_key
        if auth_token:
            client_args['auth_token'] = auth_token
        if base_url:
            client_args['base_url'] = base_url
        if proxy_url:
            client_args['http_client'] = anthropic.DefaultHttpxClient(proxy=proxy_url)
        self._client = anthropic.Anthropic(**client_args)
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort

    def generate(self, prompt: str, *, metadata=None) -> GenerationResult:  # noqa: ARG002 - Preserve public callable signature
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            output_config={'effort': self.effort},
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = '\n'.join(block.text for block in response.content if block.type == 'text')
        refusal = getattr(response, 'stop_reason', None) == 'refusal'
        if not refusal:
            try:
                return parse_generation_json(text, provider=self.provider, model=self.model)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        return GenerationResult(
            text,
            self.provider,
            self.model,
            refusal=refusal,
            limitations=[
                (
                    'Provider response was not structured JSON; claims and citations '
                    'were not validated.'
                )
            ],
        )
