"""Source scopes are enforced before each retrieval cap and throughout context expansion."""

import json
import subprocess
import sys

import pytest

from coderag.embeddings import EmbeddingMetadata
from coderag.rag_pipeline import answer
from coderag.retrieval import RetrievalConfig, retrieve
from coderag.source_filters import SourceFilters, scope_sources
from coderag.vector_store import VectorStore


def test_combination_normalization_and_directory_boundaries():
    filters = SourceFilters(
        files=['a/x.py', 'a/y.json', 'ab/z.py'], directories=['a/'], source_types=['python', 'json']
    )
    assert filters.matches({'path': 'a/x.py', 'language': 'python'})
    assert filters.matches({'path': 'a/y.json', 'language': 'json'})
    assert not filters.matches({'path': 'ab/z.py', 'language': 'python'})
    assert not filters.matches({'path': 'a/x.py', 'language': 'yaml'})
    assert not filters.matches({'path': 'a/x.py'})
    assert SourceFilters(directories=['.']).matches({'path': 'x.py'})
    assert SourceFilters(files=['a/./x.py', 'a/x.py']).files == ('a/x.py',)


@pytest.mark.parametrize(
    'values',
    [
        {'files': ['/absolute.py']},
        {'files': ['../outside.py']},
        {'directories': ['a/../b']},
        {'files': ['a\\x.py']},
        {'files': ['.']},
        {'files': ['']},
        {'source_types': ['yml']},
        {'files': 'a.py'},
        {'files': ['C:/x.py']},
    ],
)
def test_invalid_scope_paths_and_types_are_rejected(values):
    with pytest.raises(ValueError, match=r'(paths|traversal|type|list)'):
        SourceFilters(**values)


def test_lexical_filter_precedes_top_k_and_does_not_mutate_index():
    index = {
        'chunks': [
            {'id': 'a', 'path': 'noise/a.py', 'language': 'python', 'content': 'target'},
            {'id': 'z', 'path': 'api/z.py', 'language': 'python', 'content': 'target'},
        ]
    }
    result = retrieve(
        index,
        {},
        'target',
        config=RetrievalConfig(limit=1),
        filters=SourceFilters(directories=['api']),
    )
    assert [row['chunk_id'] for row in result] == ['z']
    assert len(index['chunks']) == 2


def test_structural_filter_precedes_node_cap_and_prunes_linked_chunks():
    index = {
        'chunks': [
            {'id': 'inside', 'path': 'api/a.py', 'language': 'python'},
            {'id': 'outside', 'path': 'elsewhere/b.py', 'language': 'python'},
        ]
    }
    graph = {
        'nodes': [
            {'id': 'a', 'symbol': 'dataset_id', 'chunk_id': 'outside'},
            {'id': 'z', 'kind': 'data_key', 'key': 'dataset_id'},
            {'id': 'in', 'chunk_id': 'inside'},
        ],
        'edges': [
            {'source': 'in', 'target': 'z', 'type': 'writes'},
            {'source': 'a', 'target': 'z', 'type': 'reads'},
        ],
    }
    results = retrieve(
        index,
        graph,
        'dataset_id',
        config=RetrievalConfig(limit=1),
        filters=SourceFilters(directories=['api']),
    )
    assert [row['chunk_id'] for row in results] == ['inside']
    assert results[0]['access_types'] == ['writes']


class Provider:
    def embed_query(self, _query):
        return [1.0, 0.0]


@pytest.mark.parametrize('profile', ['default', 'two_stage'])
def test_semantic_filter_precedes_vector_and_fusion_caps(tmp_path, profile):
    index = {
        'chunks': [
            {'id': 'a', 'path': 'noise/a.py', 'language': 'python'},
            {'id': 'z', 'path': 'api/z.py', 'language': 'python'},
        ]
    }
    store = VectorStore(tmp_path / 'vectors.json')
    store.upsert(
        [
            {'chunk_id': 'a', 'path': 'noise/a.py', 'vector': [1.0, 0.0]},
            {'chunk_id': 'z', 'path': 'api/z.py', 'vector': [0.0, 1.0]},
        ],
        EmbeddingMetadata('test', 2, '1'),
    )
    stores = {'v1': store, 'v2': store} if profile == 'two_stage' else store
    results = retrieve(
        index,
        {},
        'natural language question',
        config=RetrievalConfig(limit=1, semantic_profile=profile),
        semantic_store=stores,
        provider=Provider(),
        filters=SourceFilters(directories=['api'], source_types=['python']),
    )
    assert [row['chunk_id'] for row in results] == ['z']
    assert len(store.records) == 2


def test_context_expansion_cannot_escape_scope():
    index = {
        'chunks': [
            {'id': 'a', 'path': 'api/a.py', 'language': 'python', 'content': 'target'},
            {'id': 'b', 'path': 'noise/b.py', 'language': 'python', 'content': 'outside'},
        ]
    }
    graph = {
        'nodes': [
            {'id': 'na', 'chunk_id': 'a'},
            {'id': 'nb', 'chunk_id': 'b'},
            {'id': 'step', 'kind': 'gherkin_step', 'path': 'noise/c.feature'},
        ],
        'edges': [
            {'source': 'na', 'target': 'nb', 'type': 'calls'},
            {'source': 'na', 'target': 'step', 'type': 'implements'},
        ],
    }
    result = answer(
        'target', index=index, graph=graph, search_filters=SourceFilters(files=['api/a.py'])
    )
    assert [item['citation']['chunk_id'] for item in result['context']['items']] == ['a']
    assert result['context']['source_scope']['eligible_chunks'] == 1
    assert result['context']['source_scope']['indexed_chunks'] == 2
    assert not result['context']['items'][0]['relations']
    assert len(graph['nodes']) == 3
    empty, _ = scope_sources(index, graph, SourceFilters(source_types=['yaml']))
    assert not empty['chunks']


@pytest.fixture
def query(tmp_path):
    index = tmp_path / 'chunks.json'
    graph = tmp_path / 'links.json'
    index.write_text(
        json.dumps(
            {
                'chunks': [
                    {'id': str(n), 'path': f'api/{n}.py', 'language': 'python', 'content': 'target'}
                    for n in range(3)
                ]
                + [{'id': 'noise', 'path': 'noise.yaml', 'language': 'yaml', 'content': 'target'}]
            }
        )
    )
    graph.write_text('{"evidence_graph": {"nodes": [], "edges": []}}')

    def invoke(*args):
        proc = subprocess.run(
            [
                sys.executable,
                '-m',
                'coderag',
                'query',
                'target',
                '--index',
                str(index),
                '--relationships',
                str(graph),
                *args,
            ],
            capture_output=True,
            text=True,
        )
        return proc.returncode, json.loads(proc.stdout)

    return invoke, tmp_path


def test_cli_scope_metadata_report_and_pagination(query):
    invoke, root = query
    report = root / 'report.json'
    flags = ['--directory', 'api', '--source-type', 'python']
    code, first = invoke(*flags, '--page-size', '1', '--report', str(report))
    assert code == 0
    scope = first['retrieval']['source_scope']
    assert scope == {
        'filters': {'files': [], 'directories': ['api'], 'source_types': ['python']},
        'indexed_chunks': 4,
        'eligible_chunks': 3,
    }
    assert json.loads(report.read_text())['metadata']['retrieval']['source_scope'] == scope
    cursor = first['pagination']['next_cursor']
    _, second = invoke(*flags, '--cursor', cursor)
    assert first['matches'][0]['chunk_id'] != second['matches'][0]['chunk_id']
    code, changed = invoke('--directory', '.', '--source-type', 'python', '--cursor', cursor)
    assert code == 2
    assert changed['error']['code'] == 'stale_cursor'


def test_empty_scope_and_invalid_cli_filters(query):
    invoke, _ = query
    code, empty = invoke('--file', 'missing.py')
    assert code == 0
    assert empty['status'] == 'insufficient_evidence'
    assert empty['retrieval']['source_scope']['eligible_chunks'] == 0
    assert empty['retrieval']['total_matches'] is None
    assert invoke('--directory', '../bad')[0] == 2
    assert invoke('--source-type', 'unknown')[0] == 2
