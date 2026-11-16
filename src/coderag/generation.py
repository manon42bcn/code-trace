"""Contracts for evidence-grounded answer generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Claim:
    text: str
    certainty: str
    citations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GenerationResult:
    answer: str
    provider: str
    model: str
    claims: list[Claim] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    refusal: bool = False


class GenerationProvider(Protocol):
    provider: str
    model: str

    def generate(self, prompt: str, *, metadata: dict | None = None) -> GenerationResult:
        """Generate an answer from a caller-supplied grounded prompt."""
        ...


def validate_generation_result(result: GenerationResult, context: dict) -> None:
    """Reject citations that are not present in the supplied evidence context."""
    known = {item.get('chunk', {}).get('id') for item in context.get('items', [])}
    certainty_rank = {
        'not_available': 0,
        'ambiguous': 1,
        'static_candidate': 2,
        'observed_static_fact': 3,
        'runtime_observed': 4,
    }
    context_certainty = {
        item.get('chunk', {}).get('id'): item.get('certainty', 'static_candidate')
        for item in context.get('items', [])
    }
    context_citations = {
        item.get('chunk', {}).get('id'): item.get('citation', {})
        for item in context.get('items', [])
    }
    if any(not isinstance(citation, dict) for citation in result.citations):
        raise ValueError('citations must be objects')
    unknown = {citation.get('chunk_id') for citation in result.citations} - known
    claim_citations = {citation for claim in result.claims for citation in claim.citations}
    unknown_claims = claim_citations - known
    if unknown or unknown_claims:
        raise ValueError(
            f'citations reference chunks outside context: {sorted(unknown | unknown_claims)}'
        )
    for citation in result.citations:
        expected = context_citations.get(citation.get('chunk_id'), {})
        if citation.get('evidence_type') and citation.get('evidence_type') not in {
            'chunk',
            'reads',
            'writes',
            'relation',
            'source_code',
        }:
            raise ValueError('citation evidence_type is invalid')
        if citation.get('path') is not None and citation.get('path') != expected.get('path'):
            raise ValueError('citation path does not match context')
        start = citation.get('start_line', expected.get('start_line'))
        end = citation.get('end_line', expected.get('end_line'))
        context_start, context_end = expected.get('start_line'), expected.get('end_line')
        if context_start is not None and start < context_start:
            raise ValueError('citation start_line is outside context')
        if context_end is not None and end > context_end:
            raise ValueError('citation end_line is outside context')
        if start is not None and end is not None and start > end:
            raise ValueError('citation line range is invalid')
    allowed = {
        'observed_static_fact',
        'static_candidate',
        'ambiguous',
        'not_available',
        'runtime_observed',
    }
    if any(claim.certainty not in allowed for claim in result.claims):
        raise ValueError('claim has invalid certainty')
    for claim in result.claims:
        evidence = [
            context_certainty.get(citation, 'not_available') for citation in claim.citations
        ]
        if evidence and certainty_rank[claim.certainty] > max(
            certainty_rank[level] for level in evidence
        ):
            raise ValueError('claim certainty exceeds cited evidence')
    if any(not claim.citations for claim in result.claims) and not result.refusal:
        raise ValueError('non-refusal claims require citations')
    citation_ids = {citation.get('chunk_id') for citation in result.citations}
    if any(citation not in citation_ids for claim in result.claims for citation in claim.citations):
        raise ValueError('claim citation is missing from result citations')
