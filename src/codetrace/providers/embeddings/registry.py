"""Explicit registration, model resolution, and setup checks for embeddings."""

from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from ...embeddings import EmbeddingProvider
from .mlx import REQUIRED_FILES, MLXJinaProvider
from .sentence_transformers import SentenceTransformerProvider

DEFAULT_ADAPTER = 'sentence-transformers'


@dataclass(frozen=True)
class EmbeddingRegistration:
    create: Callable[[str], EmbeddingProvider]
    check_runtime: Callable[[str], str | None]
    resolve_model: Callable[[str, str | None], str]
    model_prefix: str = ''
    store_suffix: str = ''


def _sentence_model(configured, model):
    return model or configured


def _mlx_model(_configured, model):
    if not model or not Path(model).expanduser().is_absolute():
        raise ValueError('CODETRACE_EMBEDDING_MODEL must be an absolute local MLX directory')
    return str(Path(model).expanduser().resolve())


def _sentence_runtime(_model_id):
    if find_spec('sentence_transformers') is None:
        return 'Missing sentence-transformers; run make setup.'
    return None


def _mlx_runtime(model_id):
    missing = [name for name in ('mlx', 'tokenizers') if find_spec(name) is None]
    if missing:
        return f'Missing {", ".join(missing)}; run make setup EXTRAS=mlx.'
    path = Path(model_id.removeprefix('mlx:'))
    if any(not (path / name).is_file() for name in REQUIRED_FILES):
        return 'Set CODETRACE_EMBEDDING_MODEL to a complete local Jina MLX directory.'
    return None


EMBEDDING_PROVIDERS = {
    DEFAULT_ADAPTER: EmbeddingRegistration(
        lambda model: SentenceTransformerProvider(model), _sentence_runtime, _sentence_model
    ),
    'mlx': EmbeddingRegistration(MLXJinaProvider, _mlx_runtime, _mlx_model, 'mlx:', '.mlx'),
}


def embedding_adapter(model_id):
    for name, entry in EMBEDDING_PROVIDERS.items():
        if entry.model_prefix and model_id.startswith(entry.model_prefix):
            return name
    return DEFAULT_ADAPTER


def resolve_embedding_model(adapter, configured, model):
    entry = EMBEDDING_PROVIDERS.get(adapter)
    if entry is None:
        choices = ', '.join(EMBEDDING_PROVIDERS)
        raise ValueError(f'CODETRACE_EMBEDDING_PROVIDER must be one of: {choices}')
    resolved = entry.resolve_model(configured, model)
    if not isinstance(resolved, str) or not resolved.strip():
        raise ValueError('Configure a non-empty embedding model identifier')
    model_id = entry.model_prefix + resolved
    if embedding_adapter(model_id) != adapter:
        raise ValueError('Embedding model identifier conflicts with the selected adapter')
    return model_id


def embedding_runtime_issue(model_id):
    """Check the selected adapter without importing its runtime or loading weights."""
    return EMBEDDING_PROVIDERS[embedding_adapter(model_id)].check_runtime(model_id)


def build_embedding_provider(model_id):
    return EMBEDDING_PROVIDERS[embedding_adapter(model_id)].create(model_id)
