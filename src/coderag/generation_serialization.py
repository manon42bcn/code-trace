"""Safe JSON serialization for generation results."""

from __future__ import annotations

from dataclasses import asdict

from .generation import GenerationResult


def generation_result_dict(result: GenerationResult) -> dict:
    """Convert a result to JSON-safe data without Python repr fallback."""
    return asdict(result)
