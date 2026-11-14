"""Stateless continuation of a bounded, deterministic retrieval snapshot."""

import base64
import hashlib
import json
import re


class CursorError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()


def decode_cursor(token):
    try:
        if len(token) > 2048:
            raise ValueError('oversized cursor')
        data = json.loads(base64.b64decode(token, altchars=b'-_', validate=True))
        if (
            not isinstance(data, dict)
            or data.get('version') not in {1, 2}
            or type(data.get('offset')) is not int
            or data['offset'] < 1
            or type(data.get('page_size')) is not int
            or not 1 <= data['page_size'] <= 200
        ):
            raise ValueError('invalid cursor fields')
        if data['version'] == 1:
            if any(not isinstance(data.get(key), str) for key in ('snapshot', 'ranking')):
                raise ValueError('Invalid legacy cursor')
        elif (
            not isinstance(data.get('session'), str)
            or not re.fullmatch(r'[a-f0-9]{32}', data['session'])
            or not isinstance(data.get('digest'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', data['digest'])
        ):
            raise ValueError('Invalid session cursor')
        return data
    except (ValueError, TypeError) as exc:
        raise CursorError(
            'invalid_cursor', 'Invalid continuation cursor; restart the search.'
        ) from exc


def encode_cursor(data):
    return base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode()


def unique_results(results):
    unique = {}
    for result in results:
        unique.setdefault(result['chunk_id'], result)
    return list(unique.values())


def paginate(results, snapshot, *, cursor=None, page_size=None):
    """Page unique chunk IDs; never interpret the bounded pool as an exhaustive total."""
    ranked = unique_results(results)
    ranking = digest(ranked)
    size = page_size or (cursor['page_size'] if cursor else 5)
    offset = cursor['offset'] if cursor else 0
    if cursor and (cursor['snapshot'] != snapshot or cursor['ranking'] != ranking):
        raise CursorError('stale_cursor', 'Search snapshot or ranking changed; restart the search.')
    if cursor and (size != cursor['page_size'] or offset >= len(ranked)):
        raise CursorError(
            'invalid_cursor', 'Cursor page size/position invalid; restart the search.'
        )
    page = ranked[offset : offset + size]
    end = offset + len(page)
    has_more = end < len(ranked)
    return page, {
        'page_size': size,
        'offset': offset,
        'returned_matches': len(page),
        'pool_results': len(ranked),
        'has_more': has_more,
        'next_cursor': encode_cursor(
            {
                'version': 1,
                'snapshot': snapshot,
                'ranking': ranking,
                'offset': end,
                'page_size': size,
            }
        )
        if has_more
        else None,
        'snapshot': snapshot,
        'exhaustive': False,
    }
