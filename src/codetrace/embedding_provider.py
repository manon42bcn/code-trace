"""Public factory and deferred loading for embedding providers."""

from functools import cached_property

from .providers.embeddings.registry import (
    build_embedding_provider as build_embedding_provider,
    embedding_adapter as embedding_adapter,
    embedding_runtime_issue as embedding_runtime_issue,
)
from .providers.embeddings.sentence_transformers import (
    SentenceTransformerProvider as SentenceTransformerProvider,
)


class DeferredEmbeddingProvider:
    """Initialize the selected adapter only when semantic evidence is requested."""

    def __init__(self, model_id):
        self.model_id = model_id

    @cached_property
    def provider(self):
        return build_embedding_provider(self.model_id)

    @property
    def metadata(self):
        return self.provider.metadata

    def embed_query(self, text):
        return self.provider.embed_query(text)

    def embed_documents(self, texts):
        return self.provider.embed_documents(texts)
