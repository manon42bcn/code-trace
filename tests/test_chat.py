"""Exercise the local HTTP boundary and delegation to the existing answer command."""

import json
import subprocess
import sys
import threading
from http.client import HTTPConnection
from types import SimpleNamespace

import pytest

from coderag import chat


@pytest.fixture
def application(tmp_path):
    config = tmp_path / 'configuration with spaces.json'
    config.write_text(
        json.dumps(
            {
                'default_repository': 'demo',
                'repositories': {'demo': {'path': '.', 'description': 'Ejemplo'}},
                'generation': {'api_key': 'PRIVATE', 'model': 'local'},
            }
        )
    )
    return chat.ChatApplication(config, timeout=7)


@pytest.fixture
def server(application):
    with chat.ChatServer(('127.0.0.1', 0), application) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(timeout=3)


def request(server, method, path, data=None, *, authenticated=True, headers=None):
    connection = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
    default = {'Content-Type': 'application/json'}
    if authenticated:
        default['X-CodeRAG-Token'] = server.application.token
    default.update(headers or {})
    body = json.dumps(data).encode() if data is not None else None
    try:
        connection.request(method, path, body=body, headers=default)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def output():
    return {
        'generated': True,
        'repository': 'demo',
        'answer': {'answer': 'Respuesta literal\n<script>alert(1)</script>', 'citations': []},
        'context': {'items': [{'content': 'evidence', 'citation': {'path': 'main.py'}}]},
        'index_state': {'needs_update': True, 'source': {'status': 'stale'}},
    }


def test_http_delegates_answer_verbatim_with_current_python_and_no_shell(server, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(output()))

    monkeypatch.setattr(chat.subprocess, 'run', run)
    question = '--repo demo; $(touch /tmp/should-not-exist)'
    status, _, body = request(server, 'POST', '/api/answer', {'question': question, 'repo': 'demo'})
    assert status == 200
    assert json.loads(body) == output()
    command, kwargs = calls[0]
    assert command == [
        sys.executable,
        '-m',
        'coderag',
        'answer',
        '--config',
        str(server.application.config),
        '--repo',
        'demo',
        '--',
        question,
    ]
    assert kwargs['timeout'] == 7
    assert 'shell' not in kwargs
    request(
        server, 'POST', '/api/answer', {'question': 'hola', 'repo': 'demo', 'allow_remote': True}
    )
    assert calls[1][0][-3:] == ['--allow-remote', '--', 'hola']


def test_static_ui_and_repository_list_do_not_expose_configuration(server):
    status, headers, body = request(server, 'GET', '/')
    assert status == 200
    assert server.application.token.encode() in body
    assert b'__CHAT_TOKEN__' not in body
    assert headers['Cache-Control'] == 'no-store'
    assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    status, _, body = request(server, 'GET', '/api/repositories')
    assert status == 200
    assert json.loads(body) == {
        'repositories': [{'name': 'demo', 'description': 'Ejemplo'}],
        'default_repository': 'demo',
    }
    assert b'PRIVATE' not in body
    for path in ('/chat.js', '/chat.css', '/codetrace-logo-light.svg'):
        assert request(server, 'GET', path)[0] == 200
    for path in ('/config.json', '/../config.json', '/api/unknown'):
        assert request(server, 'GET', path)[0] == 404


@pytest.mark.parametrize(
    ('headers', 'authenticated'),
    [
        ({}, False),
        ({'Origin': 'https://other.example'}, True),
        ({'Host': 'other.example'}, True),
        ({'X-CodeRAG-Token': 'wrong'}, True),
    ],
)
def test_rejects_foreign_origins_hosts_and_missing_tokens(server, headers, authenticated):
    assert (
        request(
            server,
            'POST',
            '/api/answer',
            {'question': 'hola', 'repo': 'demo'},
            headers=headers,
            authenticated=authenticated,
        )[0]
        == 403
    )
    assert (
        request(server, 'GET', '/api/repositories', headers=headers, authenticated=authenticated)[0]
        == 403
    )


@pytest.mark.parametrize(
    'payload',
    [
        [],
        {},
        {'question': ' ', 'repo': 'demo'},
        {'question': 'x', 'repo': '../bad'},
        {'question': 'x', 'repo': 'demo', 'allow_remote': 'true'},
        {'question': 'x' * 12001, 'repo': 'demo'},
    ],
)
def test_invalid_questions_never_start_a_model(application, monkeypatch, payload):
    def unexpected(*_args, **_kwargs):
        pytest.fail('No child process should start')

    monkeypatch.setattr(chat.subprocess, 'run', unexpected)
    with pytest.raises(chat.ChatError):
        application.answer(payload)


@pytest.mark.parametrize(
    ('stdout', 'returncode', 'expected'),
    [
        ('not json SECRET', 1, 'JSON válido'),
        ('[]', 0, 'no válida'),
        (json.dumps({'error': {'message': 'Missing index'}}), 2, 'Missing index'),
        (json.dumps({'generated': False, 'answer': None}), 0, 'proveedor'),
    ],
)
def test_failure_response_and_recovery(application, monkeypatch, stdout, returncode, expected):
    monkeypatch.setattr(
        chat.subprocess,
        'run',
        lambda *_args, **_kwargs: SimpleNamespace(returncode=returncode, stdout=stdout),
    )
    with pytest.raises(chat.ChatError, match=expected) as caught:
        application.answer({'question': 'hola', 'repo': 'demo'})
    assert caught.value.status == 502
    assert 'SECRET' not in str(caught.value)
    assert not application.busy.locked()


def test_timeout_and_concurrent_request(application, monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired('answer', 7)

    monkeypatch.setattr(chat.subprocess, 'run', timeout)
    with pytest.raises(chat.ChatError, match='tiempo') as caught:
        application.answer({'question': 'hola', 'repo': 'demo'})
    assert caught.value.status == 504
    assert not application.busy.locked()
    with application.busy, pytest.raises(chat.ChatError) as caught:
        application.answer({'question': 'hola', 'repo': 'demo'})
    assert caught.value.status == 409


def test_http_limits_and_malformed_payload(server):
    assert request(server, 'POST', '/api/answer', 'x' * chat.MAX_REQUEST_BYTES)[0] == 413
    assert request(server, 'POST', '/api/answer', {})[0] == 400
    assert (
        request(server, 'POST', '/api/answer', {}, headers={'Content-Type': 'text/plain'})[0] == 415
    )


def test_cli_without_provider_uses_real_answer_subprocess(application, tmp_path):
    indexes = tmp_path / 'indexes'
    indexes.mkdir()
    (indexes / 'demo.chunks.json').write_text(
        json.dumps({'source_root': str(tmp_path), 'chunks': []})
    )
    (indexes / 'demo.relationships.json').write_text(json.dumps({'evidence_graph': {}}))
    application.config.write_text(json.dumps({'repositories': {'demo': {'path': str(tmp_path)}}}))
    with pytest.raises(chat.ChatError, match='proveedor'):
        application.answer({'question': 'hola', 'repo': 'demo'})


def test_chat_through_real_cli_retrieval_and_http_provider(server, tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received = []
    expected_answer = 'El identificador es order_id.\nRespuesta sin reinterpretar.'

    class ProviderHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append(payload)
            body = json.dumps(
                {
                    'response': json.dumps(
                        {
                            'answer': expected_answer,
                            'claims': [
                                {
                                    'text': 'Existe order_id',
                                    'certainty': 'static_candidate',
                                    'citations': ['a'],
                                },
                            ],
                            'citations': ['a'],
                        }
                    )
                }
            ).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    indexes = tmp_path / 'indexes'
    indexes.mkdir()
    (indexes / 'demo.chunks.json').write_text(
        json.dumps(
            {
                'chunks': [
                    {
                        'id': 'a',
                        'path': 'a.py',
                        'start_line': 1,
                        'end_line': 1,
                        'content': 'order_id = 1',
                        'language': 'python',
                    }
                ]
            }
        )
    )
    (indexes / 'demo.relationships.json').write_text(json.dumps({'evidence_graph': {}}))
    with HTTPServer(('127.0.0.1', 0), ProviderHandler) as provider:
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        try:
            server.application.config.write_text(
                json.dumps(
                    {
                        'repositories': {'demo': {}},
                        'generation': {
                            'provider': 'ollama',
                            'model': 'test-only',
                            'base_url': f'http://127.0.0.1:{provider.server_port}',
                        },
                    }
                )
            )
            status, _, body = request(
                server,
                'POST',
                '/api/answer',
                {
                    'question': 'Dónde se define order_id',
                    'repo': 'demo',
                },
            )
            assert status == 200, body
            result = json.loads(body)
            assert result['answer']['answer'] == expected_answer
            assert result['answer']['model'] == 'test-only'
            assert result['answer']['citations'] == [{'chunk_id': 'a'}]
            assert result['context']['items'][0]['content'] == 'order_id = 1'
            assert 'index_state' in result
            assert len(received) == 1
            assert 'order_id = 1' in received[0]['prompt']
        finally:
            provider.shutdown()
            thread.join(timeout=3)
