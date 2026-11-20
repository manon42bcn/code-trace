"""Reusable, timeout-isolated Python process for local chat generation."""

from __future__ import annotations

import io
import multiprocessing
import os
import threading
from contextlib import redirect_stderr, redirect_stdout
from functools import lru_cache
from subprocess import CompletedProcess, TimeoutExpired
from time import perf_counter

from .request_metrics import CHAT_REQUEST_ENV


def serve(requests, responses):
    from .__main__ import main
    from .generation_factory import build_generation_provider

    cached_provider = lru_cache(maxsize=1)(build_generation_provider)
    os.environ[CHAT_REQUEST_ENV] = '1'
    with requests, responses, open(os.devnull, 'w', encoding='utf-8') as diagnostics:
        while True:
            try:
                argv = requests.recv()
            except EOFError:
                return
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(diagnostics):
                try:
                    code = main(argv, provider_factory=cached_provider)
                except SystemExit as exc:
                    code = exc.code
                except Exception:
                    code = 1
            responses.send((code or 0, stdout.getvalue()))


class ChatWorker:
    def __init__(self):
        self._lock = threading.Lock()
        self._process = None
        self._closed = False

    def _start(self):
        context = multiprocessing.get_context('spawn')
        child_requests, requests = context.Pipe(duplex=False)
        responses, child_responses = context.Pipe(duplex=False)
        process = context.Process(target=serve, args=(child_requests, child_responses), daemon=True)
        try:
            process.start()
        except (OSError, RuntimeError):
            requests.close()
            responses.close()
            raise
        finally:
            child_requests.close()
            child_responses.close()
        self._process = process
        self._requests = requests
        self._responses = responses

    def _stop(self):
        if self._process is None:
            return
        self._requests.close()
        self._responses.close()
        if self._process.is_alive():
            self._process.terminate()
        self._process.join(timeout=1)
        if self._process.is_alive():
            self._process.kill()
            self._process.join()
        self._process.close()
        self._process = None

    def reset(self):
        with self._lock:
            self._stop()

    def close(self):
        with self._lock:
            self._closed = True
            self._stop()

    def run(self, argv, *, timeout):
        started = perf_counter()
        with self._lock:
            if self._closed:
                raise OSError('Chat worker is closed')
            if self._process is not None and not self._process.is_alive():
                self._stop()
            if self._process is None:
                self._start()
            requests, responses = self._requests, self._responses
        try:
            requests.send(argv)
            if not responses.poll(max(0, timeout - (perf_counter() - started))):
                raise TimeoutExpired(argv, timeout)
            code, stdout = responses.recv()
        except TimeoutExpired:
            self.reset()
            raise
        except (EOFError, OSError) as exc:
            self.reset()
            raise OSError('Chat worker exited before replying') from exc
        return CompletedProcess(argv, code, stdout)
