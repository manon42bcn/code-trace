"""End-to-end grounded answering with injectable generation providers."""

from __future__ import annotations

from .generation import CitationValidationError, GenerationResult, validate_generation_result
from .generation_safety import is_local_generation_provider, validate_generation_context
from .grounded_prompt import build_grounded_prompt
from .latency import timed
from .providers.llm.metrics import generate
from .request_metrics import request_metrics


def answer_query(
    query, context, provider, *, metadata=None, allow_remote=False, timings=None, history=None
):
    """Send a grounded prompt and validate the returned evidence references.

    Check generation permissions and sensitive filenames before building the
    prompt. After generation,
    validate the provider result against the same context supplied to the model.
    """
    with request_metrics(
        'answer_query',
        getattr(provider, 'provider', None),
        getattr(provider, 'model', None),
        timings,
    ) as timings:
        validate_generation_context(
            context, allow_remote=allow_remote or is_local_generation_provider(provider)
        )
        prompt = build_grounded_prompt(query, context, history=history)
        for attempt in range(2):
            measurements = {}
            try:
                result = generate(provider, prompt, measurements, metadata=metadata)
                if not isinstance(result, GenerationResult):
                    raise TypeError('generation provider must return GenerationResult')
                with timed(measurements, 'validation_seconds'):
                    validate_generation_result(result, context)
                return result
            except CitationValidationError:
                if attempt:
                    raise
                prompt += (
                    '\nThe previous result contained invalid citations. '
                    'Answer again using the same evidence. Omit path, start_line and end_line. '
                    'Copy IDs verbatim from the allowed chunk IDs in both claims and citations.'
                )
            finally:
                if timings is not None:
                    for name, seconds in measurements.items():
                        timings[name] = timings.get(name, 0) + seconds
