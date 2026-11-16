"""Verify provider checks without contacting a real LLM service."""

import json
from urllib.error import HTTPError, URLError

import pytest

from coderag import provider_check
from coderag.generation import GenerationResult


def configuration(**settings):
    return {'generation': {'provider': 'ollama', 'model': 'local', **settings}}


@pytest.mark.parametrize(
    ('raw', 'code'),
    [
        ({}, 'not_configured'),
        ({'generation': {'provider': 'none'}}, 'not_configured'),
        ({'generation': {'provider': 'ollama'}}, 'invalid_model'),
        (configuration(model=''), 'invalid_model'),
        (configuration(provider='unknown'), 'invalid_configuration'),
        (configuration(timeout_seconds=0), 'invalid_configuration'),
        (configuration(timeout_seconds=float('nan')), 'invalid_configuration'),
        (configuration(max_tokens=1.5), 'invalid_configuration'),
        (configuration(max_tokens=True), 'invalid_configuration'),
        (configuration(base_url=42), 'invalid_endpoint'),
        (configuration(base_url='ftp://localhost'), 'invalid_endpoint'),
        (configuration(base_url='http://user:secret@localhost'), 'invalid_endpoint'),
        (configuration(base_url='https://remote.example'), 'remote_consent_required'),
    ],
)
def test_invalid_configuration_does_not_construct_provider(raw, code, monkeypatch):
    def unexpected(_config):
        pytest.fail('Provider must not be constructed')

    monkeypatch.setattr(provider_check, 'build_generation_provider', unexpected)
    with pytest.raises(provider_check.ProviderCheckError, match=r'.') as exc:
        provider_check.check_provider(raw)
    assert exc.value.code == code


def test_probe_uses_configured_model_but_bounded_output(monkeypatch):
    captured = {}

    class Provider:
        def generate(self, prompt):
            captured['prompt'] = prompt
            return GenerationResult('ok', 'ollama', 'local')

    def build(config):
        captured['config'] = config
        return Provider()

    monkeypatch.setattr(provider_check, 'build_generation_provider', build)
    result = provider_check.check_provider(configuration(max_tokens=4096, timeout_seconds=42))
    assert result['generation_verified']
    assert captured['config'].max_tokens == 128
    assert captured['config'].timeout_seconds == 42
    assert captured['config'].model == 'local'
    assert 'Repository' not in captured['prompt']


@pytest.mark.parametrize(
    ('error', 'code'),
    [
        (HTTPError('http://localhost', 401, 'secret', {}, None), 'authentication_failed'),
        (HTTPError('http://localhost', 404, 'secret', {}, None), 'not_found'),
        (HTTPError('http://localhost', 429, 'secret', {}, None), 'provider_http_error'),
        (URLError('secret'), 'connection_failed'),
        (TimeoutError('secret'), 'timeout'),
        (ValueError('secret'), 'invalid_response'),
        (RuntimeError('secret'), 'provider_setup_failed'),
    ],
)
def test_provider_failures_are_actionable_without_exposing_raw_errors(monkeypatch, error, code):
    def build(_config):
        raise error

    monkeypatch.setattr(provider_check, 'build_generation_provider', build)
    with pytest.raises(provider_check.ProviderCheckError, match=r'.') as exc:
        provider_check.check_provider(configuration())
    assert exc.value.code == code
    assert 'secret' not in str(exc.value)


@pytest.mark.parametrize(('answer', 'refusal'), [('', False), ('no', True)])
def test_empty_and_refused_probes_fail(monkeypatch, answer, refusal):
    class Provider:
        def generate(self, _prompt):
            return GenerationResult(answer, 'ollama', 'local', refusal=refusal)

    monkeypatch.setattr(provider_check, 'build_generation_provider', lambda _config: Provider())
    with pytest.raises(provider_check.ProviderCheckError, match='empty answer'):
        provider_check.check_provider(configuration())


def test_cli_returns_json_for_unreadable_config(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        provider_check.main(['--config', str(tmp_path / 'missing.json')])
    assert exc.value.code == 2
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'error'
    assert result['error']['code'] == 'configuration_unreadable'


def test_explicit_remote_consent_allows_probe(monkeypatch):
    class Provider:
        def generate(self, _prompt):
            return GenerationResult('ok', 'anthropic', 'configured-model')

    monkeypatch.setattr(provider_check, 'build_generation_provider', lambda _config: Provider())
    raw = configuration(provider='anthropic', model='configured-model')
    assert provider_check.check_provider(raw, allow_remote=True)['provider'] == 'anthropic'
