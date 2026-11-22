"""Shared repository-aware semantic configuration for preparation and queries."""

import os
from functools import cached_property
from pathlib import Path

from .embedding_provider import DeferredEmbeddingProvider, embedding_adapter
from .generation_config import read_generation_dotenv
from .providers.embeddings.registry import (
    DEFAULT_ADAPTER,
    EMBEDDING_PROVIDERS,
    resolve_embedding_model,
)
from .repository_paths import repository_index_path

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
STORE_KEYS = ('semantic_v1_store', 'semantic_v2_store')


def embedding_model(configured):
    env = read_generation_dotenv()
    provider = os.getenv('CODETRACE_EMBEDDING_PROVIDER', env.get('CODETRACE_EMBEDDING_PROVIDER'))
    model = os.getenv('CODETRACE_EMBEDDING_MODEL', env.get('CODETRACE_EMBEDDING_MODEL'))
    return resolve_embedding_model(
        (provider or DEFAULT_ADAPTER).strip(),
        configured,
        model.strip() if model else None,
    )


def resolve_retrieval(raw, config_path, index_path, *, resolve_paths=True):
    root = Path(config_path).resolve().parent
    index_path = Path(index_path).resolve()
    settings = dict(raw.get('retrieval') or {})
    for name, repository in raw.get('repositories', {}).items():
        if repository_index_path(raw, config_path, name) == index_path:
            settings.update(repository.get('retrieval') or {})
            break
    enabled = settings.pop('semantic_enabled', None)
    paths = [settings.pop(key, None) for key in STORE_KEYS]
    configured_model = settings.pop('embedding_model', MODEL)
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError('semantic_enabled must be true or false')
    if enabled is False:
        return settings, None, configured_model
    model = embedding_model(configured_model)
    adapter = EMBEDDING_PROVIDERS[embedding_adapter(model)]
    if (enabled is True or adapter.store_suffix) and not any(paths):
        stem = index_path.name.removesuffix('.chunks.json').removesuffix('.json')
        paths = [index_path.with_name(f'{stem}.vectors-{version}.json') for version in ('v1', 'v2')]
    if bool(paths[0]) != bool(paths[1]):
        raise ValueError('semantic retrieval requires both v1 and v2 stores')
    if not all(paths):
        return settings, None, model
    logical_paths = [(root / path).absolute() for path in paths]
    if adapter.store_suffix:
        logical_paths = [
            path.with_suffix(adapter.store_suffix + path.suffix) for path in logical_paths
        ]
    paths = [path.resolve() for path in logical_paths]
    if paths[0] == paths[1] or index_path in paths:
        raise ValueError('semantic stores must have distinct paths separate from the chunks index')
    settings.setdefault('semantic_profile', 'two_stage')
    return (
        settings,
        dict(zip(('v1', 'v2'), paths if resolve_paths else logical_paths, strict=True)),
        model,
    )


def _validate_store(store, expected, *, require_config_version=False):
    found = store.metadata
    if (
        found is None
        or found.model_id != expected.model_id
        or found.dimensions != expected.dimensions
        or (require_config_version and found.config_version != expected.config_version)
    ):
        raise ValueError(
            'Semantic vectors are incompatible with the configured embedding model; rebuild them'
        )


class DeferredVectorStore:
    """Keep vector files off the exact-lookup path."""

    def __init__(self, path, provider, *, require_config_version):
        self.path = path
        self.provider = provider
        self.require_config_version = require_config_version

    @cached_property
    def store(self):
        from .vector_store import VectorStore

        store = VectorStore(self.path)
        _validate_store(
            store, self.provider.metadata, require_config_version=self.require_config_version
        )
        return store

    def search(self, vector, **options):
        return self.store.search(vector, **options)


def active_vector_paths(settings, paths, model, *, sqlite_backend=False):
    if paths is None or settings.get('mode') == 'lexical':
        return None
    allow_missing = sqlite_backend or embedding_adapter(model) != DEFAULT_ADAPTER
    if allow_missing and settings.get('mode', 'configured') == 'configured':
        if any(not path.is_file() for path in paths.values()):
            return None
    return paths


def load_retrieval(raw, config_path, index_path, *, index=None, sqlite_backend=False):
    from .retrieval import RetrievalConfig

    settings, paths, model = resolve_retrieval(raw, config_path, index_path)
    strict_version = embedding_adapter(model) != DEFAULT_ADAPTER
    paths = active_vector_paths(settings, paths, model, sqlite_backend=sqlite_backend)
    retrieval = RetrievalConfig.from_mapping(settings)
    if paths is None:
        if retrieval.mode == 'semantic':
            raise ValueError('Semantic mode requires semantic_enabled and prepared stores')
        return retrieval, None, None
    from .embedding_provider import build_embedding_provider
    from .vector_store import VectorStore

    missing = next((path for path in paths.values() if not path.is_file()), None)
    if missing is not None:
        raise ValueError(
            f'Semantic vectors missing: {missing}; run make indexes or code-trace embed first'
        )
    if sqlite_backend and index is None:
        provider = DeferredEmbeddingProvider(model)
        stores = {
            key: DeferredVectorStore(path, provider, require_config_version=strict_version)
            for key, path in paths.items()
        }
        return retrieval, stores, provider

    stores = {key: VectorStore(path) for key, path in paths.items()}
    if index is not None:
        from .preparation import validate_vectors_for_index

        validate_vectors_for_index(index, stores, model)
    provider = build_embedding_provider(model)
    for store in stores.values():
        _validate_store(store, provider.metadata, require_config_version=strict_version)
    return retrieval, stores, provider
