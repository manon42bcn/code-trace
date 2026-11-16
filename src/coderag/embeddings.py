"""Versioned contracts for local embedding providers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

EMBEDDING_CONTRACT_VERSION = '1'


@dataclass(frozen=True)
class EmbeddingMetadata:
    model_id: str
    dimensions: int
    config_version: str
    text_version: str = 'v1'
    contract_version: str = EMBEDDING_CONTRACT_VERSION

    def __post_init__(self):
        if not self.model_id or self.dimensions <= 0 or not self.config_version:
            raise ValueError('invalid embedding metadata')


class EmbeddingProvider(Protocol):
    """Provider contract; implementations must remain usable offline by default."""

    metadata: EmbeddingMetadata

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per input text, preserving order."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Return one vector for a query."""
        ...


def validate_vectors(vectors: Sequence[Sequence[float]], metadata: EmbeddingMetadata) -> None:
    """Reject malformed provider output at the contract boundary."""
    if any(len(vector) != metadata.dimensions for vector in vectors):
        raise ValueError('embedding dimension does not match provider metadata')
    if any(not isinstance(value, (int, float)) for vector in vectors for value in vector):
        raise ValueError('embedding values must be numeric')
