"""Prepare local semantic stores for a configured repository."""

import argparse
import json
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path

from .embedding_enrichment import enrich_chunks_from_graph
from .embedding_index import update_embedding_store
from .repository_paths import repository_index_path, repository_relationships_path
from .semantic_config import resolve_retrieval
from .vector_store import VectorStore


def prepare(config_path, repo, *, provider=None, progress=None):
    config_path = Path(config_path).resolve()
    raw = json.loads(config_path.read_text(encoding='utf-8'))
    index_path = repository_index_path(raw, config_path, repo)
    _, paths, model = resolve_retrieval(raw, config_path, index_path)
    if paths is None:
        return {'repository': repo, 'semantic': 'disabled'}
    index = json.loads(index_path.read_text(encoding='utf-8'))
    graph_path = repository_relationships_path(config_path, repo)
    graph = json.loads(graph_path.read_text(encoding='utf-8'))['evidence_graph']
    if provider is None:
        from .embedding_provider import build_embedding_provider

        provider = build_embedding_provider(model)
    # Both representations use the current text renderer; v2 adds graph metadata.
    provider.metadata = replace(provider.metadata, text_version='v2')
    enriched = enrich_chunks_from_graph(index, graph)
    report = {'repository': repo, 'stores': {}}
    reusable = None
    for version, data in (('v1', index), ('v2', enriched)):
        store = VectorStore(paths[version])
        # A model/configuration change requires full re-embedding, never mixed vectors.
        if store.metadata is not None and store.metadata != provider.metadata:
            store.records = {}
        store.metadata = provider.metadata
        report['stores'][version] = update_embedding_store(
            data,
            repo,
            provider,
            store,
            reusable=reusable,
            progress=partial(progress, version) if progress else None,
        )
        if version == 'v1':
            reusable = store.records
    return report


def _report_progress(repo, version, done, total, reused):
    print(  # noqa: T201 - progress on stderr preserves the JSON output
        f'{repo} {version}: {done}/{total} nuevos · {reused} reutilizados',
        file=sys.stderr,
        flush=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--repo', required=True)
    args = parser.parse_args(argv)
    try:
        report = prepare(args.config, args.repo, progress=partial(_report_progress, args.repo))
        print(json.dumps(report))  # noqa: T201 - CLI output
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        parser.exit(2, f'Error: {exc}\n')
