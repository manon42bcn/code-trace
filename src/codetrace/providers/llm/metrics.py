"""Collect common and adapter-specific timings for generation calls."""

from ...latency import timed


def generate(provider, prompt, timings, *, metadata=None):
    try:
        with timed(timings, 'generation_seconds'):
            if metadata is None:
                return provider.generate(prompt)
            return provider.generate(prompt, metadata=metadata)
    finally:
        provider_timings = getattr(provider, 'last_timings', None)
        if timings is not None and isinstance(provider_timings, dict):
            timings.update(provider_timings)
