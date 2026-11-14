"""Parse provider text into validated structured generation data."""

from __future__ import annotations

import json

from .generation import Claim, GenerationResult


def parse_generation_json(text: str, *, provider: str, model: str) -> GenerationResult:
    """Parse strict JSON or a JSON fenced block from a provider response."""
    raw = text.strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    data = json.loads(raw)
    claims = [
        Claim(item['text'], item['certainty'], item.get('citations', []))
        for item in data.get('claims', [])
    ]
    citations = [
        ({'chunk_id': citation} if isinstance(citation, str) else citation)
        for citation in data.get('citations', [])
    ]
    return GenerationResult(
        answer=data.get('answer', ''),
        provider=provider,
        model=model,
        claims=claims,
        citations=citations,
        limitations=data.get('limitations', []),
        refusal=bool(data.get('refusal', False)),
    )
