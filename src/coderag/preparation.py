"""Shared offline preparation checks for doctor and query readiness."""

import hashlib
import json
import shlex
import sys
import time
from pathlib import Path

from .artifact_state import file_stamp, link_signature
from .core import discover, discover_paths
from .embeddings import validate_vectors
from .repository_paths import index_output

QUICK_TTL = 30


class VectorPreparationError(ValueError):
    pass


class ReadinessError(ValueError):
    def __init__(self, report, *, freshness=False):
        super().__init__(
            'Source freshness is not verified.'
            if freshness
            else 'Prepared artifacts are inconsistent; rebuild the selected repository.'
        )
        self.code = 'source_not_fresh' if freshness else 'preparation_inconsistent'
        self.readiness = report


def rebuild_command(config_path, repo=None):
    command = (
        f'{shlex.quote(sys.executable)} '
        f'{shlex.quote(str(Path(__file__).resolve().parents[2] / "scripts/build_indexes.py"))} '
        f'--config {shlex.quote(str(Path(config_path).resolve()))}'
    )
    return command + (f' --repo {shlex.quote(repo)}' if repo else '') + ' --incremental'


def validate_vectors_for_index(index, stores, model):
    ids = {chunk['id'] for chunk in index['chunks']}
    for version, store in stores.items():
        if store.metadata is None or store.metadata.model_id != model:
            raise VectorPreparationError(
                f'{version}: missing vectors or incompatible model metadata'
            )
        if set(store.records) != ids:
            raise VectorPreparationError(
                f'{version}: vector chunk identifiers differ from the index'
            )
        try:
            validate_vectors([row['vector'] for row in store.records.values()], store.metadata)
        except (ValueError, TypeError, KeyError) as exc:
            raise VectorPreparationError(f'{version}: invalid vector dimensions/records') from exc


def relationship_checks(
    index, links, config, config_path, repo=None, *, full_dependencies=False, index_path=None
):
    """Return unverifiable legacy warnings; fail only on known mismatches."""
    warnings, dependencies = [], {}
    selected = repo or links.get('source_repository')
    if repo and links.get('source_repository') not in {None, repo}:
        raise ValueError('Relationships belong to a different repository')
    if (
        selected in config.get('repositories', {})
        and links.get('preparation_signature') is not None
    ):
        if links['preparation_signature'] != link_signature(config, selected):
            raise ValueError('Linking configuration changed; rebuild relationships')
    else:
        warnings.append('Linking configuration provenance unavailable; regenerate links.')
    sources = links.get('index_sources')
    if not isinstance(sources, dict) or not sources or not index.get('created_at') or not selected:
        return ['Relationship/index provenance is missing; regenerate indexes and links.'], {}
    if selected not in sources or not isinstance(sources[selected], dict):
        raise ValueError('Relationships do not identify the selected index')
    if sources[selected].get('created_at') != index['created_at']:
        raise ValueError('Relationships do not match the current index; rebuild links')
    if index_path and sources[selected].get('file_stamp') is not None:
        if sources[selected]['file_stamp'] != file_stamp(index_path):
            raise ValueError('Selected index changed since linking; rebuild links')
    for name, metadata in sources.items():
        if not isinstance(metadata, dict):
            raise ValueError('Invalid relationship provenance metadata')
        if name == selected:
            continue
        if config_path is None or not config.get('repositories'):
            warnings.append(f'Dependency {name} cannot be verified without its configuration.')
            continue
        path = Path(config_path).resolve().parent / index_output(config, name)
        if not path.is_file():
            raise ValueError(f'Relationship dependency index missing: {name}')
        dependencies[str(path)] = metadata.get('file_stamp') or file_stamp(path)
        if metadata.get('file_stamp') is not None:
            if metadata['file_stamp'] != file_stamp(path):
                raise ValueError(f'Relationship dependency index changed: {name}')
        elif full_dependencies:
            dependency = json.loads(path.read_text(encoding='utf-8'))
            if metadata.get('created_at') != dependency.get('created_at'):
                raise ValueError(f'Relationship dependency index changed: {name}')
        else:
            warnings.append(f'Dependency {name} has no file provenance; regenerate links.')
    if links.get('missing_dependencies'):
        raise ValueError('Relationships report missing dependency indexes')
    return warnings, dependencies


def source_spec(index, raw, repo, index_path):
    settings = raw.get('indexing')
    source = index.get('source_root')
    if not isinstance(source, str):
        return None
    if not isinstance(settings, dict):
        return {'root': source, 'git': index.get('git')}
    patterns = [
        *settings.get('exclude', []),
        *raw.get('repositories', {}).get(repo, {}).get('exclude', []),
    ]
    effective = {**settings, 'exclude': patterns}

    def signature(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    return {
        'root': source,
        'git': index.get('git'),
        'discovery': {
            key: effective.get(key, default)
            for key, default in (('languages', []), ('language_overrides', {}), ('exclude', []))
        },
        'manifest': index.get('source_manifest'),
        'stats': index.get('source_stats'),
        'expected_settings': signature(index['indexing_settings'])
        if isinstance(index.get('indexing_settings'), dict)
        else None,
        'current_settings': signature(effective),
        'index_mtime_ns': Path(index_path).stat().st_mtime_ns,
    }


def assess_source_files(spec, mode='quick', previous=None):
    now = time.time()
    if (
        mode == 'quick'
        and previous
        and previous.get('mode') == 'quick'
        and previous.get('valid_until', 0) > now
    ):
        return {**previous, 'reused': True}
    result = {
        'mode': mode,
        'status': 'unknown',
        'verification': 'none',
        'checked_at': now,
        'valid_until': now + QUICK_TTL if mode == 'quick' else now,
        'reused': False,
    }
    if not spec:
        return {
            **result,
            'message': 'Source/indexing provenance unavailable; supply configuration or reindex.',
        }
    if not isinstance(spec.get('manifest'), dict):
        return {
            **result,
            'message': 'Source manifest unavailable; reindex once for freshness checks.',
        }
    root = Path(spec['root'])
    if not root.is_dir():
        return {
            **result,
            'message': 'Source working tree is unavailable; querying indexed snapshot.',
        }
    if spec['expected_settings'] is None:
        return {**result, 'message': 'Indexing configuration provenance unavailable; reindex once.'}
    if spec['expected_settings'] != spec['current_settings']:
        return {**result, 'status': 'stale', 'message': 'Indexing settings changed since indexing.'}
    discovery = spec['discovery']
    try:
        if mode == 'full':
            stats = {}
            current = {
                path.relative_to(root).as_posix(): hashlib.sha256(text.encode()).hexdigest()
                for path, _, text in discover(
                    root,
                    set(discovery['languages']),
                    discovery['language_overrides'],
                    discovery['exclude'],
                    source_stats=stats,
                )
            }
            changed = current != spec['manifest']
            if not changed and any(value is None for value in stats.values()):
                return {**result, 'message': 'Source changed while reading; retry verification.'}
            verification = 'sha256'
        else:
            current = {
                path.relative_to(root).as_posix(): file_stamp(path)
                for path, _ in discover_paths(
                    root,
                    set(discovery['languages']),
                    discovery['language_overrides'],
                    discovery['exclude'],
                )
            }
            verification = 'metadata'
            if isinstance(spec.get('stats'), dict):
                changed = current != spec['stats']
            else:
                changed = set(current) != set(spec['manifest']) or any(
                    stamp[3] > spec['index_mtime_ns'] for stamp in current.values()
                )
                if not changed:
                    return {
                        **result,
                        'verification': verification,
                        'message': 'Legacy index lacks source timestamp manifest; reindex once.',
                    }
        return {
            **result,
            'verification': verification,
            'status': 'stale' if changed else 'current',
            'message': 'Source/settings differ from the indexed snapshot.'
            if changed
            else 'Eligible source snapshot matches the selected verification method.',
        }
    except (OSError, ValueError, TypeError) as exc:
        return {**result, 'message': f'Source verification unavailable: {type(exc).__name__}.'}


def assess_sources(spec, mode='quick', previous=None):
    if (
        mode == 'quick'
        and previous
        and previous.get('mode') == 'quick'
        and previous.get('valid_until', 0) > time.time()
    ):
        return {**previous, 'reused': True}
    from .git_state import compare_git

    git_state = (
        compare_git(spec['root'], spec.get('git'))
        if spec
        else {
            'status': 'unknown',
            'message': 'Source root unavailable; Git cannot be checked.',
            'reference_changed': False,
            'indexed': None,
            'current': None,
        }
    )
    source = assess_source_files(spec, mode)
    if mode == 'quick' and (
        git_state['reference_changed']
        or (
            source['status'] == 'stale'
            and (git_state.get('current') or {}).get('status') == 'available'
        )
    ):
        # Changed commits/branches or timestamps alone do not prove changed indexed contents.
        source = assess_source_files(spec, 'full')
        source.update(mode='quick', valid_until=source['checked_at'] + QUICK_TTL)
    return {**source, 'git': git_state}


def needs_update(source):
    return {'current': False, 'stale': True}.get(source['status'])


def readiness_report(spec, checks, mode='quick', previous=None):
    source = assess_sources(spec, mode, previous)
    errors = any(check['status'] == 'error' for check in checks)
    warnings = (
        any(check['status'] == 'warning' for check in checks)
        or source['status'] != 'current'
        or source['git']['status'] in {'changed', 'unknown'}
    )
    return {
        'schema_version': 1,
        'status': 'error' if errors else 'warning' if warnings else 'ok',
        'checks': checks,
        'source': source,
        'git': source['git'],
        'needs_update': needs_update(source),
        'limitations': [
            'Quick checks normally use metadata; Git reference changes trigger hashes; cached 30s.',
            'Freshness describes assessment time, not a locked working-tree snapshot.',
            'No generation provider is probed and no artifacts are rebuilt.',
        ],
    }


def inspect_preparation(index, links, raw, config_path, index_path, repo=None):
    checks, dependencies = [], {}
    remedy = (
        rebuild_command(config_path, repo)
        if config_path
        else ('Rebuild chunks/links with their original configuration; run coderag doctor.')
    )

    def add(code, status, message):
        checks.append({'code': code, 'status': status, 'message': message, 'remedy': remedy})

    try:
        chunks = index['chunks']
        ids = [chunk['id'] for chunk in chunks]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate chunk identifiers in index')
        if repo in raw.get('repositories', {}) and index.get('source_root'):
            expected = (
                Path(config_path).resolve().parent / raw['repositories'][repo]['path']
            ).resolve()
            if Path(index['source_root']).resolve() != expected:
                raise ValueError('Index belongs to a different configured source directory')
        add('index', 'ok', 'Chunk identifiers/source identity checked.')
        warnings, dependencies = relationship_checks(
            index, links, raw, config_path, repo, index_path=index_path
        )
        add(
            'relationships',
            'ok' if not warnings else 'warning',
            'Relationship provenance matches.' if not warnings else '; '.join(warnings),
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        add('artifacts', 'error', str(exc))
    if index.get('skipped_files') or index.get('diagnostics'):
        add(
            'coverage',
            'warning',
            'Index has skipped files/parser diagnostics; inspect coderag analyze.',
        )
    spec = source_spec(index, raw, repo, index_path)
    return {
        'spec': spec,
        'checks': checks,
        'dependencies': dependencies,
        'remedy': remedy,
    }


def evaluate_readiness(state, mode='quick', previous=None, *, require_fresh=False):
    if mode == 'off':
        return {
            'schema_version': 1,
            'status': 'skipped',
            'checks': [],
            'source': {'status': 'not_checked', 'mode': 'off'},
            'limitations': ['Preparation checking explicitly disabled.'],
        }
    mode = 'full' if require_fresh else mode
    report = readiness_report(
        state['spec'], state['checks'], mode, previous.get('source') if previous else None
    )
    report['remedy'] = state['remedy']
    if report['status'] == 'error':
        raise ReadinessError(report)
    if require_fresh and report['source']['status'] != 'current':
        raise ReadinessError(report, freshness=True)
    return report
