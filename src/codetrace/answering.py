"""End-to-end grounded answering with injectable generation providers."""

from __future__ import annotations

from .generation import GenerationResult, validate_generation_result
from .generation_safety import validate_generation_context
from .grounded_prompt import build_grounded_prompt


def answer_query(query, context, provider, *, metadata=None, allow_remote=False):
    """Generate and validate an answer from an evidence context."""
    is_local = getattr(provider, 'provider', None) == 'ollama'
    validate_generation_context(context, allow_remote=allow_remote or is_local)
    prompt = build_grounded_prompt(query, context)
    result = provider.generate(prompt, metadata=metadata)
    if not isinstance(result, GenerationResult):
        raise TypeError('generation provider must return GenerationResult')
    validate_generation_result(result, context)
    return result
