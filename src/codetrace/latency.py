"""Latency measurement helpers for the retrieval and generation pipeline."""

from __future__ import annotations

import time
from contextlib import contextmanager


@contextmanager
def timed(metrics: dict | None, name: str):
    if metrics is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        metrics[name] = time.perf_counter() - started
