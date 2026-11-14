"""Evaluation metrics for grounded RAG answers."""

from __future__ import annotations


def evaluate_answer(result, *, relevant_citations, required_claims=0):
    """Measure citation coverage and structured-answer completeness."""
    cited = {citation.get('chunk_id') for citation in result.citations}
    relevant = set(relevant_citations)
    claims = len(result.claims)
    claim_coverage = (
        (sum(bool(claim.citations) for claim in result.claims) / claims) if claims else 1.0
    )
    return {
        'citation_recall': len(cited & relevant) / len(relevant) if relevant else 1.0,
        'invalid_citations': len(cited - relevant),
        'claim_coverage': claim_coverage,
        'claims': claims,
        'claims_requirement_met': claims >= required_claims,
        'refusal': result.refusal,
        'has_limitations': bool(result.limitations),
    }
