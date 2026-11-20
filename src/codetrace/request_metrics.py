"""Append local request measurements without recording request content."""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from .latency import timed

CHAT_REQUEST_ENV = 'CODETRACE_CHAT_REQUEST'
HISTORY_PATH = Path('indexes/reports/requests.jsonl')
_active = ContextVar('request_metrics_active', default=False)
_logger = logging.getLogger(__name__)


@contextmanager
def request_metrics(source, provider, model, timings=None, *, details=None):
    """Measure one request, allowing nested stages to share its measurements."""
    if _active.get():
        yield timings
        return
    measurements = {} if timings is None else timings
    started = datetime.now(timezone.utc)
    status = 'ok'
    error_type = None
    token = _active.set(True)
    try:
        with timed(measurements, 'total_seconds'):
            yield measurements
    except BaseException as exc:
        status = 'error'
        error_type = type(exc).__name__
        raise
    finally:
        _active.reset(token)
        _append(
            {
                'started_at': started.isoformat(),
                'source': source,
                'provider': provider,
                'model': model,
                'status': status,
                'error_type': error_type,
                'timings': measurements,
                **(details or {}),
            }
        )


def _append(event):
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(event, ensure_ascii=True) + '\n').encode('utf-8')
        fd = os.open(HISTORY_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            if os.write(fd, line) != len(line):
                raise OSError('Incomplete metrics write')
        finally:
            os.close(fd)
    except (OSError, TypeError, ValueError):
        _logger.warning('Could not write local request metrics')
