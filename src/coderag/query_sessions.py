"""Private, bounded disk snapshots for evidence pagination without rerunning retrieval."""

import json
import math
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

from .artifact_state import file_stamp
from .query_pagination import CursorError, digest, encode_cursor
from .source_filters import scope_sources

MAX_BYTES = 16 * 1024 * 1024
MAX_SESSIONS = 32
DEFAULT_TTL = 3600
KIND = 'coderag-query-session'


def session_directory(args):
    if args.session_dir:
        return args.session_dir.expanduser().resolve()
    if args.config:
        return args.config.resolve().parent / 'indexes/.query_sessions'
    return args.index.resolve().parent / '.query_sessions'


def request_identity(args, filters):
    def path(value):
        return str(value.resolve()) if value else None

    return {
        'query': args.query,
        'config': path(args.config),
        'index': path(args.index),
        'relationships': path(args.relationships),
        'default_repo': args.default_repo,
        'repo': args.repo,
        'retrieval_mode': args.retrieval_mode,
        'limit': args.limit,
        'budget_profile': args.budget_profile,
        'filters': filters.describe(),
        'readiness': args.readiness,
        'require_fresh': args.require_fresh,
    }


def file_stamps(paths):
    result = {}
    for path in paths:
        path = Path(path).absolute()
        result[str(path)] = file_stamp(path)
    return result


def validate_files(watched):
    try:
        current = file_stamps(watched)
    except OSError as exc:
        raise CursorError(
            'stale_cursor', 'Search artifact unavailable; restart the search.'
        ) from exc
    if current != watched:
        raise CursorError('stale_cursor', 'Search artifacts changed; restart the search.')


def evidence_view(index, graph, ranked, filters):
    scoped, graph = scope_sources(index, graph, filters)
    ids = {row['chunk_id'] for row in ranked}
    chunks = [chunk for chunk in scoped['chunks'] if chunk['id'] in ids]
    if {chunk['id'] for chunk in chunks} != ids:
        raise ValueError('Retrieval references chunks outside the selected index')
    primary = {node['id'] for node in graph.get('nodes', []) if node.get('chunk_id') in ids}
    edges = [
        edge
        for edge in graph.get('edges', [])
        if edge.get('source') in primary or edge.get('target') in primary
    ]
    keep = primary | {edge.get(side) for edge in edges for side in ('source', 'target')}
    view = {
        'nodes': [node for node in graph.get('nodes', []) if node['id'] in keep],
        'edges': edges,
    }
    scope = (
        {
            'filters': filters.describe(),
            'indexed_chunks': len(index['chunks']),
            'eligible_chunks': len(scoped['chunks']),
        }
        if filters.active
        else None
    )
    return {'chunks': chunks}, {'evidence_graph': view}, scope


def _prune(directory, now):
    remaining = []
    for path in directory.glob('session-*.json'):
        if not re.fullmatch(r'session-[a-f0-9]{32}\.json', path.name) or path.is_symlink():
            continue
        try:
            stat = path.stat()
            if stat.st_size > MAX_BYTES:
                continue
            data = json.loads(path.read_bytes())
            if data.get('kind') != KIND or not isinstance(data.get('expires_at'), (int, float)):
                continue
            if data['expires_at'] <= now:
                path.unlink(missing_ok=True)
                (directory / path.name.replace('session-', 'readiness-', 1)).unlink(missing_ok=True)
            else:
                remaining.append((stat.st_mtime_ns, path))
        except (OSError, ValueError, AttributeError):
            continue
    for _, path in sorted(remaining)[: max(0, len(remaining) - MAX_SESSIONS + 1)]:
        path.unlink(missing_ok=True)
        (directory / path.name.replace('session-', 'readiness-', 1)).unlink(missing_ok=True)


def save_session(directory, payload, *, ttl=DEFAULT_TTL):
    if not 1 <= ttl <= 86400:
        raise ValueError('Session TTL must be between 1 and 86400 seconds')
    now = time.time()
    data = {
        'kind': KIND,
        'schema_version': 1,
        'created_at': now,
        'expires_at': now + ttl,
        'payload': payload,
    }
    checksum = digest(data)
    content = json.dumps(data, separators=(',', ':')).encode()
    if len(content) > MAX_BYTES:
        raise CursorError('session_too_large', 'Reduce --limit or use --no-session.')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    _prune(directory, now)
    identifier = uuid.uuid4().hex
    path = directory / f'session-{identifier}.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return data, identifier, checksum


def load_session(directory, cursor, request):
    path = Path(directory) / f'session-{cursor["session"]}.json'
    try:
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError('Invalid session file')
        data = json.loads(path.read_bytes())
        if (
            data.get('kind') != KIND
            or data.get('schema_version') != 1
            or not isinstance(data.get('expires_at'), (int, float))
            or not math.isfinite(data['expires_at'])
            or digest(data) != cursor['digest']
        ):
            raise ValueError('Invalid session integrity/schema')
        payload = data['payload']
        if not isinstance(payload, dict):
            raise ValueError('Invalid session payload')
    except FileNotFoundError as exc:
        raise CursorError(
            'session_missing', 'Session was removed/evicted; restart the search.'
        ) from exc
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        raise CursorError('invalid_session', 'Invalid session data; restart the search.') from exc
    if data['expires_at'] <= time.time():
        raise CursorError('session_expired', 'Session expired; restart the search.')
    if payload['request'] != request:
        raise CursorError('stale_cursor', 'Question/scope/settings changed; restart the search.')
    validate_files(payload['watched'])
    return data


def session_page(data, identifier, checksum, *, cursor=None, page_size=None):
    payload = data['payload']
    ranked = payload['ranked']
    size = cursor['page_size'] if cursor else page_size
    offset = cursor['offset'] if cursor else 0
    if cursor and ((page_size is not None and page_size != size) or offset >= len(ranked)):
        raise CursorError(
            'invalid_cursor', 'Cursor page size/position invalid; restart the search.'
        )
    page = ranked[offset : offset + size]
    end = offset + len(page)
    return page, {
        'page_size': size,
        'offset': offset,
        'returned_matches': len(page),
        'pool_results': len(ranked),
        'has_more': end < len(ranked),
        'next_cursor': encode_cursor(
            {
                'version': 2,
                'session': identifier,
                'digest': checksum,
                'offset': end,
                'page_size': size,
            }
        )
        if end < len(ranked)
        else None,
        'snapshot': payload['snapshot'],
        'exhaustive': False,
        'session': {
            'id': identifier,
            'created_at': data['created_at'],
            'expires_at': data['expires_at'],
            'reused': cursor is not None,
        },
    }


def readiness_assessment(directory, cursor, previous):
    """Read only the small mutable freshness assessment, bound to an immutable session digest."""
    path = Path(directory) / f'readiness-{cursor["session"]}.json'
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            return previous
        data = json.loads(path.read_bytes())
        source = data['source']
        if (
            data.get('session_digest') != cursor['digest']
            or data.get('checksum') != digest(source)
            or not isinstance(source, dict)
            or source.get('mode') != 'quick'
            or not isinstance(source.get('checked_at'), (int, float))
            or not isinstance(source.get('valid_until'), (int, float))
            or not 0 <= source['valid_until'] - source['checked_at'] <= 30
            or source['checked_at'] > time.time()
        ):
            return previous
        return {**previous, 'source': source}
    except (OSError, ValueError, KeyError, TypeError):
        return previous


def save_readiness_assessment(directory, cursor, report):
    source = report['source']
    path = Path(directory) / f'readiness-{cursor["session"]}.json'
    data = {'session_digest': cursor['digest'], 'source': source, 'checksum': digest(source)}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(data).encode())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
