"""Check the configured generation provider with a small synthetic request."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import sys
import time
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from .generation_config import GenerationConfig
from .generation_factory import build_generation_provider

PROBE = (
    'Return exactly this JSON object, with no additional text: '
    '{"answer":"ok","claims":[],"citations":[],"limitations":[],"refusal":false}'
)


class ProviderCheckError(ValueError):
    """An actionable check failure that does not expose credentials or response bodies."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def is_loopback(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            raise ValueError('invalid endpoint')
        if parsed.username or parsed.password:
            raise ValueError('endpoint credentials are not supported')
        # Validate the port without connecting.
        _ = parsed.port
    except ValueError as exc:
        raise ProviderCheckError(
            'invalid_endpoint', 'Use an HTTP(S) endpoint without URL credentials.'
        ) from exc
    if parsed.hostname.lower() == 'localhost':
        return True
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def check_provider(raw, *, allow_remote=False):
    if not isinstance(raw, dict) or not isinstance(raw.get('generation'), dict):
        raise ProviderCheckError(
            'not_configured', 'Configure the generation object in config.json.'
        )
    try:
        config = GenerationConfig.from_mapping(raw['generation'])
    except (TypeError, ValueError) as exc:
        raise ProviderCheckError(
            'invalid_configuration', 'Invalid generation provider or limits.'
        ) from exc
    if config.provider == 'none':
        raise ProviderCheckError('not_configured', 'Generation is disabled (provider: none).')
    if not isinstance(config.model, str) or not config.model.strip():
        raise ProviderCheckError('invalid_model', 'Configure a non-empty generation model.')
    if not raw['generation'].get('model'):
        raise ProviderCheckError(
            'invalid_model', 'Set generation.model explicitly before checking it.'
        )
    if (
        not isinstance(config.max_tokens, int)
        or isinstance(config.max_tokens, bool)
        or not isinstance(config.timeout_seconds, (int, float))
        or isinstance(config.timeout_seconds, bool)
        or not math.isfinite(config.timeout_seconds)
    ):
        raise ProviderCheckError(
            'invalid_configuration', 'Use integer output limits and a finite timeout.'
        )
    if config.base_url is not None and not isinstance(config.base_url, str):
        raise ProviderCheckError('invalid_endpoint', 'Use an HTTP(S) endpoint string.')
    local = (
        is_loopback(config.base_url or 'http://localhost:11434')
        if config.provider == 'ollama'
        else False
    )
    if config.base_url and config.provider != 'ollama':
        is_loopback(config.base_url)  # Validate a custom endpoint without exposing it in output.
    if not local and not allow_remote:
        raise ProviderCheckError(
            'remote_consent_required', 'Repeat with --allow-remote for a remote generation probe.'
        )
    # Exercise the same provider adapter as a real query, with no repository content.
    bounded = replace(config, max_tokens=min(config.max_tokens, 128))
    try:
        provider = build_generation_provider(bounded)
        result = provider.generate(PROBE)
    except Exception as exc:
        status = getattr(exc, 'status_code', None)
        if isinstance(exc, HTTPError):
            status = exc.code
        if status in {401, 403}:
            code, message = (
                'authentication_failed',
                'Check provider credentials and model permissions.',
            )
        elif status == 404:
            code, message = (
                'not_found',
                'Check the model name and endpoint; for Ollama, pull the configured model.',
            )
        elif status is not None:
            code, message = (
                'provider_http_error',
                f'Provider returned HTTP {status}; check its service and quota.',
            )
        elif isinstance(exc, (TimeoutError,)) or 'Timeout' in type(exc).__name__:
            code, message = (
                'timeout',
                'Provider timed out; check the service or increase generation.timeout_seconds.',
            )
        elif isinstance(exc, URLError) or 'Connection' in type(exc).__name__:
            code, message = (
                'connection_failed',
                'Cannot connect to provider; check its service, endpoint, and proxy.',
            )
        elif isinstance(exc, RuntimeError):
            code, message = (
                'provider_setup_failed',
                'Check provider dependencies (Anthropic requires the llm extra).',
            )
        elif isinstance(exc, ValueError):
            code, message = (
                'invalid_response',
                'Provider did not return valid structured generation data.',
            )
        else:
            code, message = (
                'provider_failed',
                'Provider probe failed; check credentials, configuration, and service logs.',
            )
        raise ProviderCheckError(code, message) from exc
    if result.refusal or not isinstance(result.answer, str) or not result.answer.strip():
        raise ProviderCheckError(
            'invalid_response', 'Provider refused the probe or returned an empty answer.'
        )
    return {
        'provider': config.provider,
        'model': config.model,
        'generation_verified': True,
        'limitations': result.limitations,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config.json'))
    parser.add_argument('--allow-remote', action='store_true')
    args = parser.parse_args(argv)
    started = time.perf_counter()
    output = {'schema_version': '1', 'status': 'error', 'generation_verified': False, 'error': None}
    exit_code = 0
    try:
        raw = json.loads(args.config.read_text(encoding='utf-8'))
        with redirect_stdout(sys.stderr):
            output.update(check_provider(raw, allow_remote=args.allow_remote))
        output['status'] = 'ok'
    except ProviderCheckError as exc:
        output['error'] = {'code': exc.code, 'message': str(exc)}
        exit_code = 2
    except (OSError, ValueError):
        output['error'] = {
            'code': 'configuration_unreadable',
            'message': 'Cannot read a valid JSON configuration.',
        }
        exit_code = 2
    output['latency_seconds'] = round(time.perf_counter() - started, 3)
    print(json.dumps(output, ensure_ascii=False))  # noqa: T201 - CLI output
    if exit_code:
        raise SystemExit(exit_code)
