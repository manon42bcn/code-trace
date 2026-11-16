"""Optional local sentence-transformers embedding provider."""

from __future__ import annotations

from collections.abc import Sequence

from .embeddings import EmbeddingMetadata, validate_vectors


class SentenceTransformerProvider:
    """Embed text locally through sentence-transformers.

    The dependency and model are loaded only when this provider is instantiated.
    """

    def __init__(
        self,
        model_id: str = 'sentence-transformers/all-MiniLM-L6-v2',
        *,
        config_version: str = 'v1',
        device: str | None = None,
    ):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                'sentence-transformers is required; install with: uv sync --extra embeddings'
            ) from exc
        kwargs = {'device': device} if device else {}
        self._model = SentenceTransformer(model_id, **kwargs)
        dimensions = self._model.get_embedding_dimension()
        self.metadata = EmbeddingMetadata(model_id, dimensions, config_version)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(list(texts), convert_to_numpy=True)
        result = vectors.tolist()
        validate_vectors(result, self.metadata)
        return result

    def embed_query(self, text: str) -> list[float]:
        result = self.embed_documents([text])
        return result[0]
