"""Loopback-only web chat backed by the existing answer CLI."""

import argparse
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .request_metrics import CHAT_REQUEST_ENV

WEB = Path(__file__).with_name('web')
MAX_REQUEST_BYTES = 32768
ENGLISH_ERRORS = {
    'Se esperaba un objeto JSON': 'Expected a JSON object',
    'La pregunta debe tener entre 1 y 12000 caracteres': (
        'The question must be between 1 and 12000 characters'
    ),
    'Selecciona un repositorio configurado': 'Select a configured repository',
    'allow_remote debe ser booleano': 'allow_remote must be a boolean',
    'Hay una consulta en curso. Espera a que termine.': 'A request is already running.',
    'Se agotó el tiempo de la consulta. Puedes volver a intentarlo.': (
        'The request timed out. You can try again.'
    ),
    (
        'CodeTrace no devolvió JSON válido. Revisa el proveedor y los índices con codetrace doctor.'
    ): ('CodeTrace returned invalid JSON. Check the provider and indices with codetrace doctor.'),
    'Respuesta de CodeTrace no válida': 'Invalid response from CodeTrace',
    'No se pudo completar la consulta': 'The request could not be completed',
    'Configura un proveedor de generación disponible en config.json.': (
        'Configure an available generation provider in config.json.'
    ),
    'Host no permitido': 'Host not allowed',
    'Origen no permitido': 'Origin not allowed',
    'Sesión no válida; recarga el chat': 'Invalid session. Reload the chat.',
    'Recurso no encontrado': 'Resource not found',
    'No se pudo leer la configuración o la interfaz local.': (
        'Could not read the configuration or local interface.'
    ),
    'Se requiere application/json': 'Expected application/json',
    'Tamaño no válido': 'Invalid request size',
    'Petición vacía o demasiado grande': 'Empty or oversized request',
    'JSON no válido': 'Invalid JSON',
    'No se pudo ejecutar CodeTrace. Revisa la configuración local.': (
        'Could not run CodeTrace. Check the local configuration.'
    ),
}


class ChatError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class ChatApplication:
    def __init__(self, config, *, timeout=600):
        self.config = Path(config).resolve()
        dotenv = dotenv_values('.env', interpolate=False) if Path('.env').is_file() else {}
        self.language = (os.getenv('CHAT_LANG', dotenv.get('CHAT_LANG')) or 'es').strip().lower()
        if self.language not in {'es', 'en'}:
            raise ValueError('CHAT_LANG must be es or en')
        self.timeout = timeout
        self.token = secrets.token_urlsafe(32)
        self.busy = threading.Lock()
        self.repositories()  # Fail before opening a browser if configuration is invalid.

    def repositories(self):
        raw = json.loads(self.config.read_text(encoding='utf-8'))
        repositories = raw.get('repositories')
        if not isinstance(repositories, dict) or not repositories:
            raise ValueError('La configuración debe incluir repositories')
        return {
            'repositories': [
                {'name': name, 'description': item.get('description', '')}
                for name, item in repositories.items()
            ],
            'default_repository': raw.get('default_repository'),
        }

    def answer(self, request):
        if not isinstance(request, dict):
            raise ChatError('Se esperaba un objeto JSON')
        question, repo = request.get('question'), request.get('repo')
        if not isinstance(question, str) or not question.strip() or len(question) > 12000:
            raise ChatError('La pregunta debe tener entre 1 y 12000 caracteres')
        names = {item['name'] for item in self.repositories()['repositories']}
        if not isinstance(repo, str) or repo not in names:
            raise ChatError('Selecciona un repositorio configurado')
        remote = request.get('allow_remote', False)
        if not isinstance(remote, bool):
            raise ChatError('allow_remote debe ser booleano')
        if not self.busy.acquire(blocking=False):
            raise ChatError('Hay una consulta en curso. Espera a que termine.', 409)
        try:
            command = [
                sys.executable,
                '-m',
                'codetrace',
                'answer',
                '--config',
                str(self.config),
                '--repo',
                repo,
            ]
            if remote:
                command.append('--allow-remote')
            # End of options keeps question text from becoming CLI arguments.
            command.extend(['--', question.strip()])
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    timeout=self.timeout,
                    check=False,
                    env={**os.environ, CHAT_REQUEST_ENV: '1'},
                )
            except subprocess.TimeoutExpired as exc:
                raise ChatError(
                    'Se agotó el tiempo de la consulta. Puedes volver a intentarlo.', 504
                ) from exc
            try:
                output = json.loads(result.stdout)
            except (json.JSONDecodeError, TypeError) as exc:
                # Stderr may include provider secrets. Keep it in the local process, off the API.
                raise ChatError(
                    'CodeTrace no devolvió JSON válido. '
                    'Revisa el proveedor y los índices con codetrace doctor.',
                    502,
                ) from exc
            if not isinstance(output, dict):
                raise ChatError('Respuesta de CodeTrace no válida', 502)
            if result.returncode or output.get('error'):
                error = output.get('error') or {}
                message = error.get('message', 'No se pudo completar la consulta')
                raise ChatError(str(message), 502)
            if not output.get('generated') or not isinstance(output.get('answer'), dict):
                raise ChatError(
                    'Configura un proveedor de generación disponible en config.json.', 502
                )
            return output
        finally:
            self.busy.release()


class ChatServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, application):
        self.application = application
        super().__init__(address, ChatHandler)
        self.origin = f'http://127.0.0.1:{self.server_port}'


class ChatHandler(BaseHTTPRequestHandler):
    server_version = 'CodeTraceChat'

    def log_message(self, *_args):
        # Do not log questions, source excerpts or configuration.
        return

    def send(self, status, payload, content_type='application/json; charset=utf-8'):
        body = (
            json.dumps(payload, ensure_ascii=False).encode()
            if isinstance(payload, dict)
            else payload
        )
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header(
            'Content-Security-Policy',
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def send_error_message(self, status, message):
        if self.server.application.language == 'en':
            message = ENGLISH_ERRORS.get(message, message)
        self.send(status, {'error': message})

    def trusted(self, *, api=False):
        expected = urlsplit(self.server.origin).netloc
        if self.headers.get('Host') != expected:
            raise ChatError('Host no permitido', 403)
        origin = self.headers.get('Origin')
        if origin is not None and origin != self.server.origin:
            raise ChatError('Origen no permitido', 403)
        if api and not hmac.compare_digest(
            self.headers.get('X-CodeRAG-Token', ''), self.server.application.token
        ):
            raise ChatError('Sesión no válida; recarga el chat', 403)

    def do_GET(self):
        try:
            self.trusted(api=self.path.startswith('/api/'))
            if self.path == '/api/repositories':
                self.send(200, self.server.application.repositories())
                return
            files = {
                '/': ('index.html', 'text/html'),
                '/chat.js': ('chat.js', 'text/javascript'),
                '/chat.css': ('chat.css', 'text/css'),
                '/codetrace-logo-light.svg': ('codetrace-logo-light.svg', 'image/svg+xml'),
            }
            if self.path not in files:
                raise ChatError('Recurso no encontrado', 404)
            name, content_type = files[self.path]
            body = (WEB / name).read_bytes()
            if name == 'index.html':
                application = self.server.application
                body = body.replace(b'__CHAT_TOKEN__', application.token.encode())
                body = body.replace(b'__CHAT_LANG__', application.language.encode())
            self.send(200, body, content_type + '; charset=utf-8')
        except ChatError as exc:
            self.send_error_message(exc.status, str(exc))
        except (OSError, ValueError, TypeError, AttributeError):
            self.send_error_message(500, 'No se pudo leer la configuración o la interfaz local.')

    def do_POST(self):
        try:
            self.trusted(api=True)
            if self.path != '/api/answer':
                raise ChatError('Recurso no encontrado', 404)
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                raise ChatError('Se requiere application/json', 415)
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError as exc:
                raise ChatError('Tamaño no válido') from exc
            if not 0 < size <= MAX_REQUEST_BYTES or self.headers.get('Transfer-Encoding'):
                raise ChatError('Petición vacía o demasiado grande', 413)
            try:
                request = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError) as exc:
                raise ChatError('JSON no válido') from exc
            self.send(200, self.server.application.answer(request))
        except ChatError as exc:
            self.send_error_message(exc.status, str(exc))
        except (OSError, ValueError, TypeError, AttributeError):
            self.send_error_message(
                500, 'No se pudo ejecutar CodeTrace. Revisa la configuración local.'
            )


def main(argv=None):
    parser = argparse.ArgumentParser(prog='code-trace chat', description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config.json'))
    parser.add_argument(
        '--port', type=int, default=8765, help='Puerto local (0: asignar uno libre)'
    )
    parser.add_argument(
        '--timeout', type=int, default=600, help='Tiempo máximo por consulta, segundos'
    )
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535 or args.timeout < 1:
        parser.error('Puerto o tiempo máximo no válido')
    try:
        application = ChatApplication(args.config, timeout=args.timeout)
        server = ChatServer(('127.0.0.1', args.port), application)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.exit(2, f'No se pudo iniciar el chat: {exc}\n')
    with server:
        print(f'CodeTrace: {server.origin} · Ctrl+C para detener', flush=True)  # noqa: T201
        if not args.no_browser:
            webbrowser.open(server.origin)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
