"""Shared repository-aware semantic configuration for preparation and queries."""

from pathlib import Path

from .repository_paths import repository_index_path

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
STORE_KEYS = ('semantic_v1_store', 'semantic_v2_store')


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
    model = settings.pop('embedding_model', MODEL)
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError('semantic_enabled must be true or false')
    if enabled is False:
        return settings, None, model
    if enabled is True and not any(paths):
        stem = index_path.name.removesuffix('.chunks.json').removesuffix('.json')
        paths = [index_path.with_name(f'{stem}.vectors-{version}.json') for version in ('v1', 'v2')]
    if bool(paths[0]) != bool(paths[1]):
        raise ValueError('semantic retrieval requires both v1 and v2 stores')
    if not all(paths):
        return settings, None, model
    logical_paths = [(root / path).absolute() for path in paths]
    paths = [path.resolve() for path in logical_paths]
    if paths[0] == paths[1] or index_path in paths:
        raise ValueError('semantic stores must have distinct paths separate from the chunks index')
    settings.setdefault('semantic_profile', 'two_stage')
    return (
        settings,
        dict(zip(('v1', 'v2'), paths if resolve_paths else logical_paths, strict=True)),
        model,
    )


def load_retrieval(raw, config_path, index_path, *, index=None):
    from .retrieval import RetrievalConfig

    settings, paths, model = resolve_retrieval(raw, config_path, index_path)
    retrieval = RetrievalConfig.from_mapping(settings)
    if paths is None or retrieval.mode == 'lexical':
        if retrieval.mode == 'semantic':
            raise ValueError('Semantic mode requires semantic_enabled and prepared stores')
        return retrieval, None, None
    from .embedding_provider import SentenceTransformerProvider
    from .vector_store import VectorStore

    for path in paths.values():
        if not path.is_file():
            raise ValueError(f'Semantic vectors missing: {path}; run make indexes first')
    stores = {key: VectorStore(path) for key, path in paths.items()}
    if index is not None:
        from .preparation import validate_vectors_for_index

        validate_vectors_for_index(index, stores, model)
    provider = SentenceTransformerProvider(model)
    for store in stores.values():
        if (
            store.metadata is None
            or store.metadata.model_id != model
            or store.metadata.dimensions != provider.metadata.dimensions
        ):
            raise ValueError(
                'Semantic vectors are incompatible with the configured embedding '
                'model; rebuild them'
            )
    return retrieval, stores, provider
