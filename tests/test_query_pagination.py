"""Continuation is bounded, repeatable and invalidated by snapshot changes."""

import json
import subprocess
import sys

import pytest

from coderag.query_pagination import CursorError, decode_cursor, paginate


@pytest.fixture
def search(tmp_path):
    index = tmp_path / 'chunks.json'
    links = tmp_path / 'relationships.json'
    config = tmp_path / 'config.json'
    index.write_text(
        json.dumps(
            {
                'chunks': [
                    {
                        'id': str(n),
                        'path': f'{n}.py',
                        'content': 'order_id = 123',
                        'start_line': 1,
                        'end_line': 1,
                    }
                    for n in range(7)
                ]
            }
        )
    )
    links.write_text(json.dumps({'evidence_graph': {'nodes': [], 'edges': []}}))
    config.write_text(json.dumps({'retrieval': {'limit': 5}}))
    argv = [
        'order_id',
        '--index',
        str(index),
        '--relationships',
        str(links),
        '--config',
        str(config),
        '--limit',
        '10',
    ]

    def invoke(*extra):
        proc = subprocess.run(
            [sys.executable, '-m', 'coderag', 'query', *argv, *extra],
            capture_output=True,
            text=True,
        )
        return proc.returncode, json.loads(proc.stdout)

    return invoke, index, links, config, tmp_path


def test_pages_are_repeatable_distinct_and_bounded(search):
    invoke, _, _, _, _ = search
    code, first = invoke('--page-size', '2')
    assert code == 0
    assert first['pagination']['pool_results'] == 5
    assert first['retrieval']['effective_limit'] == 5
    assert first['context']['effective_limits']['expansion_depth'] == 0
    cursor = first['pagination']['next_cursor']
    code, second = invoke('--cursor', cursor)
    assert code == 0
    assert second == invoke('--cursor', cursor)[1]
    _, last = invoke('--cursor', second['pagination']['next_cursor'])
    ids = [m['chunk_id'] for page in (first, second, last) for m in page['matches']]
    assert len(ids) == len(set(ids)) == 5
    assert last['pagination']['has_more'] is False
    assert last['pagination']['next_cursor'] is None
    assert last['retrieval']['total_matches'] is None
    assert len(last['matches']) == 1


@pytest.mark.parametrize('artifact', ['index', 'links', 'config'])
def test_artifact_changes_reject_cursor(search, artifact):
    invoke, index, links, config, _ = search
    _, first = invoke('--page-size', '2')
    path = {'index': index, 'links': links, 'config': config}[artifact]
    data = json.loads(path.read_text())
    data['changed'] = True
    path.write_text(json.dumps(data))
    code, result = invoke('--cursor', first['pagination']['next_cursor'])
    assert code == 2
    assert result['error']['code'] == 'stale_cursor'


def test_budget_excluded_matches_are_still_listed_and_reports_preserve_pages(search):
    invoke, _, _, _, root = search
    code, first = invoke(
        '--page-size',
        '3',
        '--max-chunks',
        '1',
        '--max-chars',
        '4',
        '--report',
        str(root / 'report.json'),
    )
    assert code == 0
    assert len(first['matches']) == 3
    assert len(first['evidence']) == 1
    assert sum(m['evidence_included'] for m in first['matches']) == 1
    assert first['evidence'][0]['truncated']
    metadata = json.loads((root / 'report.json').read_text())['metadata']
    assert metadata['matches'] == first['matches']
    assert metadata['pagination'] == first['pagination']
    _, next_page = invoke('--cursor', first['pagination']['next_cursor'])
    assert not (
        {m['chunk_id'] for m in first['matches']} & {m['chunk_id'] for m in next_page['matches']}
    )


@pytest.mark.parametrize(
    'flags',
    [
        ('--page-size', '0'),
        ('--page-size', '201'),
        ('--cursor', 'garbage'),
        ('--page-size', '2', '--mode', 'answer'),
        ('--page-size', '2', '--resolve-only'),
    ],
)
def test_invalid_page_requests_fail_as_json(search, flags):
    invoke, _, _, _, _ = search
    assert invoke(*flags)[0] == 2


def test_changed_query_limit_and_page_size_rejected(search):
    invoke, _, _, _, _ = search
    _, first = invoke('--page-size', '2')
    cursor = first['pagination']['next_cursor']
    assert invoke('--cursor', cursor, '--limit', '4')[1]['error']['code'] == 'stale_cursor'
    assert invoke('--cursor', cursor, '--page-size', '3')[1]['error']['code'] == 'invalid_cursor'


def test_empty_pool_has_no_cursor(search):
    invoke, index, _, _, _ = search
    index.write_text('{"chunks": []}')
    code, result = invoke('--page-size', '2')
    assert code == 0
    assert result['matches'] == []
    assert result['pagination']['next_cursor'] is None


def test_pool_deduplication_and_changed_ranking():
    results = [
        {'chunk_id': 'a', 'score': 1},
        {'chunk_id': 'a', 'score': 1},
        {'chunk_id': 'b', 'score': 1},
    ]
    page, info = paginate(results, 'snapshot', page_size=1)
    assert page[0]['chunk_id'] == 'a'
    assert info['pool_results'] == 2
    cursor = decode_cursor(info['next_cursor'])
    page, _ = paginate(results, 'snapshot', cursor=cursor)
    assert page[0]['chunk_id'] == 'b'
    with pytest.raises(CursorError, match='ranking changed'):
        paginate(list(reversed(results)), 'snapshot', cursor=cursor)
