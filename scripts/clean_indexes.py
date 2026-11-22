"""Remove generated index artifacts for the configured repositories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codetrace.providers.embeddings.registry import EMBEDDING_PROVIDERS
from codetrace.repository_paths import (
    index_output,
    repository_relationships_path,
    transitive_dependencies,
)
from codetrace.semantic_config import (
    STORE_KEYS,
    repository_retrieval_settings,
    vector_paths_with_suffix,
)
from codetrace.sqlite_index import sqlite_index_path


def _vector_file(path):
    """Recognize a CodeTrace vector store without loading its vectors."""
    with path.open(encoding='utf-8') as file:
        prefix = file.read(16384)
    try:
        header = prefix[: prefix.index('"records"')].rstrip().removesuffix(',') + '}'
        data = json.loads(header)
    except ValueError:
        return False
    metadata = data.get('metadata')
    return (
        data.get('schema_version') == 1
        and isinstance(metadata, dict)
        and {'model_id', 'dimensions', 'config_version'} <= metadata.keys()
    )


def clean_indexes(config_path, selected=None):
    """Remove snapshots, relationships, and vectors for every registered adapter."""
    config_path = config_path.resolve()
    raw = json.loads(config_path.read_text(encoding='utf-8'))
    repositories = raw.get('repositories')
    if not isinstance(repositories, dict) or not repositories:
        raise ValueError('config.json must contain a non-empty repositories object')
    names = dict.fromkeys(
        name
        for selected_name in selected or repositories
        for name in [selected_name, *transitive_dependencies(raw, selected_name)]
    )
    root = config_path.parent
    suffixes = {entry.store_suffix for entry in EMBEDDING_PROVIDERS.values()}
    standard = set()
    custom = set()
    for name in names:
        index = root / index_output(raw, name)
        standard.update(
            (index, sqlite_index_path(index), repository_relationships_path(config_path, name))
        )
        bases = [index.with_name(f'{name}.vectors-{version}.json') for version in ('v1', 'v2')]
        settings = repository_retrieval_settings(raw, name)
        overrides = [settings[key] for key in STORE_KEYS if settings.get(key)]
        for suffix in suffixes:
            standard.update(vector_paths_with_suffix(bases, root, suffix))
            custom.update(vector_paths_with_suffix(overrides, root, suffix))

    standard = {path.parent.resolve() / path.name for path in standard}
    custom = {path.parent.resolve() / path.name for path in custom} - standard
    candidates = []
    for path in sorted(standard | custom):
        if not path.is_symlink() and not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Expected a regular index file: {path}')
        if path in custom and not _vector_file(path):
            raise ValueError(f'Configured vector path is not a CodeTrace vector file: {path}')
        candidates.append(path)
    for path in candidates:
        path.unlink()
    return candidates


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--repo', action='append')
    args = parser.parse_args(argv)
    try:
        removed = clean_indexes(args.config, args.repo)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.exit(2, f'Error: {exc}\n')
    print(f'Removed {len(removed)} generated index files.')  # noqa: T201


if __name__ == '__main__':
    main()
