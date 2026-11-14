"""Read-only preparation diagnostics; no model loading or network unless requested."""

import argparse
import importlib.util
import json
import shlex
import sys
from pathlib import Path

from .preparation import (
    assess_sources,
    relationship_checks,
    source_spec,
    validate_vectors_for_index,
)
from .repository_paths import repository_index_path, repository_relationships_path
from .semantic_config import resolve_retrieval


def read_object(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object')
    return data


def diagnose(config_path, *, repos=None, full=False, probe=False, allow_remote=False):
    """Collect independent checks and corrective commands, without modifying artifacts."""
    config_path = Path(config_path).resolve()
    checks = []

    def add(code, status, message, repo=None, remedy=None, **details):
        checks.append(
            {
                'code': code,
                'status': status,
                'repository': repo,
                'message': message,
                'remedy': remedy,
                **details,
            }
        )

    output = {'schema_version': '1', 'config': str(config_path), 'checks': checks}
    try:
        raw = read_object(config_path)
        catalog = raw.get('repositories')
        if not isinstance(catalog, dict) or not catalog:
            raise ValueError('Configure a non-empty repositories object')
        indexing = raw.get('indexing')
        if not isinstance(indexing, dict) or not isinstance(indexing.get('languages'), list):
            raise ValueError('Configure indexing.languages as a list')
        if not isinstance(indexing.get('chunking'), dict):
            raise ValueError('Configure indexing.chunking as an object')
        names = repos or list(catalog)
        if any(name not in catalog for name in names):
            raise ValueError('Unknown selected repository')
        add('configuration', 'ok', 'Configuration readable; repository selection valid.')
    except (OSError, ValueError) as exc:
        add(
            'configuration',
            'error',
            str(exc),
            remedy='Correct the configuration path/repositories.',
        )
        return finish(output)
    add('python', 'ok' if sys.version_info >= (3, 10) else 'error', sys.executable)
    if sys.prefix == sys.base_prefix:
        add(
            'environment',
            'warning',
            'Python is not running in a virtual environment.',
            remedy='Run make setup, then use the CodeTrace .venv/bin/python.',
        )
    else:
        add('environment', 'ok', f'Virtual environment: {sys.prefix}')
    for module in ('yaml',):
        add(
            'dependency',
            'ok' if importlib.util.find_spec(module) else 'error',
            module,
            remedy='Run make setup in the CodeTrace checkout.',
        )
    for name in dict.fromkeys(names):
        rebuild = (
            f'{shlex.quote(sys.executable)} '
            f'{shlex.quote(str(Path(__file__).resolve().parents[2] / "scripts/build_indexes.py"))} '
            f'--config {shlex.quote(str(config_path))} --repo {shlex.quote(name)} --incremental'
        )
        try:
            settings = catalog[name]
            if not isinstance(settings, dict):
                raise ValueError('Repository settings must be an object')
            source = (config_path.parent / settings['path']).resolve()
            if not source.is_dir():
                raise ValueError(f'Repository directory unavailable: {source}')
            add('source', 'ok', str(source), name)
            index_path = repository_index_path(raw, config_path, name)
            index = read_object(index_path)
            chunks = index['chunks']
            if not isinstance(chunks, list) or any(not isinstance(c, dict) for c in chunks):
                raise ValueError('Index chunks must be a list of objects')
            ids = {c['id'] for c in chunks}
            if len(ids) != len(chunks):
                raise ValueError('Duplicate chunk identifiers')
            if Path(index['source_root']).resolve() != source:
                raise ValueError('Index belongs to a different source directory')
            add('index', 'ok', f'{len(chunks)} chunks.', name)
            if index.get('skipped_files') or index.get('diagnostics'):
                add(
                    'index_coverage',
                    'warning',
                    'Index has skipped files or parser diagnostics.',
                    name,
                    'Inspect coderag analyze output and fix indexing diagnostics.',
                )
            check_freshness(raw, index, index_path, full, add, name, rebuild)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            add('index', 'error', str(exc), name, rebuild)
            continue
        try:
            links = read_object(repository_relationships_path(config_path, name))
            if not isinstance(links.get('evidence_graph'), dict):
                raise ValueError('Missing evidence_graph object')
            if not links.get('index_sources') or not index.get('created_at'):
                raise ValueError('Missing relationship/index provenance metadata')
            warnings, _ = relationship_checks(
                index, links, raw, config_path, name, full_dependencies=True, index_path=index_path
            )
            if warnings:
                add('relationships_provenance', 'warning', '; '.join(warnings), name, rebuild)
            add('relationships', 'ok', 'Relationship index snapshots match.', name)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            add('relationships', 'error', str(exc), name, rebuild)
        try:
            from .retrieval import RetrievalConfig

            retrieval, stores, model = resolve_retrieval(raw, config_path, index_path)
            RetrievalConfig.from_mapping(retrieval)
            if stores is None:
                add('vectors', 'skipped', 'Semantic retrieval disabled.', name)
            else:
                from .vector_store import VectorStore

                loaded = {key: VectorStore(path) for key, path in stores.items()}
                validate_vectors_for_index(index, loaded, model)

                add(
                    'vectors', 'ok', 'Model metadata, dimensions and chunk identifiers match.', name
                )
                add(
                    'embedding_runtime',
                    'ok' if importlib.util.find_spec('sentence_transformers') else 'error',
                    'Embedding package availability (model not loaded).',
                    name,
                    'Run make setup.',
                )
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            add('vectors', 'error', str(exc), name, rebuild)
    if probe:
        from .provider_check import ProviderCheckError, check_provider

        try:
            check_provider(raw, allow_remote=allow_remote)
            add('provider', 'ok', 'Synthetic generation probe succeeded.')
        except ProviderCheckError as exc:
            add(
                'provider',
                'error',
                f'{exc.code}: {exc}',
                remedy='Run coderag check-provider --help.',
            )
    else:
        add(
            'provider', 'skipped', 'Generation provider not probed; use --check-provider if needed.'
        )
    return finish(output)


def check_freshness(raw, index, index_path, full, add, name, rebuild):
    """Check only eligible indexed sources, using the indexer's discovery rules."""
    spec = source_spec(index, raw, name, index_path)
    # Source lookup uses source_root from the index; config is needed only for indexing settings.
    result = assess_sources(spec, 'full' if full else 'quick')
    status = (
        'ok'
        if result['status'] == 'current'
        else 'error'
        if (full and result['status'] == 'stale')
        else 'warning'
    )
    add('freshness', status, result['message'], name, rebuild if status != 'ok' else None)
    git_state = result['git']
    git_status = {'current': 'ok', 'not_applicable': 'skipped'}.get(git_state['status'], 'warning')
    git_message = git_state['message']
    if git_status != 'skipped':
        indexed = git_state.get('indexed') or {}
        current = git_state.get('current') or {}
        git_message += (
            f' Indexed: {indexed.get("commit")}; current: {current.get("commit")};'
            f' relation: {git_state.get("relation")}.'
        )
    add(
        'git',
        git_status,
        git_message,
        name,
        rebuild if git_status == 'warning' else None,
        git=git_state,
        needs_update={'current': False, 'stale': True}.get(result['status']),
    )

    if not full and result.get('verification') != 'sha256':
        add(
            'freshness_scope',
            'warning',
            'Quick metadata checks cannot prove byte freshness; use --full.',
            name,
        )


def finish(output):
    statuses = {check['status'] for check in output['checks']}
    output['status'] = (
        'error' if 'error' in statuses else 'warning' if 'warning' in statuses else 'ok'
    )
    output['limitations'] = [
        'Full verification covers only files discoverable under current indexing limits.',
        'No embedding model is loaded; vector text hashes and runtime model availability '
        'are not verified.',
    ]
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config.json'))
    parser.add_argument(
        '--repo', action='append', help='Repeat to select repositories; default all'
    )
    parser.add_argument(
        '--full', action='store_true', help='Compare complete eligible source hashes'
    )
    parser.add_argument('--check-provider', action='store_true')
    parser.add_argument('--allow-remote', action='store_true')
    parser.add_argument('--output-format', choices=('text', 'json'), default='text')
    args = parser.parse_args(argv)
    from contextlib import redirect_stdout

    with redirect_stdout(sys.stderr):
        result = diagnose(
            args.config,
            repos=args.repo,
            full=args.full,
            probe=args.check_provider,
            allow_remote=args.allow_remote,
        )
    if args.output_format == 'json':
        print(json.dumps(result, ensure_ascii=False, indent=2))  # noqa: T201
    else:
        print(f'Doctor: {result["status"]}')  # noqa: T201
        for check in result['checks']:
            label = f'{check["repository"]}: ' if check['repository'] else ''
            print(f'[{check["status"]}] {label}{check["code"]}: {check["message"]}')  # noqa: T201
            if check['remedy'] and check['status'] in {'error', 'warning'}:
                print(f'  Fix: {check["remedy"]}')  # noqa: T201
        for limitation in result['limitations']:
            print(f'Note: {limitation}')  # noqa: T201
    if result['status'] == 'error':
        raise SystemExit(2)
