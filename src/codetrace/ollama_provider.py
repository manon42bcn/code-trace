"""Optional local Ollama generation provider."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from .generation import GenerationResult
from .structured_generation import parse_generation_json


class OllamaProvider:
    provider = 'ollama'

    def __init__(
        self,
        *,
        model: str,
        base_url: str = 'http://localhost:11434',
        timeout: float = 120.0,
        max_tokens: int = 4096,
    ):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_tokens = max_tokens

    def generate(self, prompt: str, *, metadata=None) -> GenerationResult:  # noqa: ARG002 - Preserve public callable signature
        request = Request(
            f'{self.base_url}/api/generate',
            data=json.dumps(
                {
                    'model': self.model,
                    'prompt': prompt,
                    'stream': False,
                    'format': 'json',
                    'options': {'num_predict': self.max_tokens},
                }
            ).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode())
        text = payload.get('response', '')
        try:
            return parse_generation_json(text, provider=self.provider, model=self.model)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError('Ollama returned invalid structured generation JSON') from exc
