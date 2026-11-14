"""Natural planning is inspectable and never changes the semantic/generation question."""

import json
import subprocess
import sys

import pytest

from coderag.query_planning import plan_query
from coderag.rag_pipeline import answer
from coderag.retrieval import RetrievalConfig, retrieve
from coderag.search import search_hybrid


def test_plan_preserves_input_and_extracts_only_written_identifiers():
    text = '¿Dónde se implementa upload_dataset y Client.sendOrder?'
    plan = plan_query(text)
    assert plan['input'] == plan['semantic_query'] == text
    assert plan['lexical_transformed']
    assert plan['identifier_anchors'] == ['upload_dataset', 'Client.sendOrder']
    assert 'donde' not in plan['lexical_terms']
    assert {'upload', 'dataset', 'client', 'send', 'order'} <= set(plan['lexical_terms'])
    assert plan_query('order_id')['lexical_mode'] == 'literal'
    assert plan_query(text, exact=True)['lexical_mode'] == 'literal'
    assert plan_query('Where is src/api.py used?')['intent'] == 'natural_language'
    assert plan_query('src/api.py')['intent'] == 'exact_path'


def test_natural_overlap_recovers_definition_without_literal_question_substring():
    index = {
        'chunks': [
            {'id': 'a', 'path': 'schema.py', 'symbol': 'dataset_schema', 'content': 'schema'},
            {
                'id': 'z',
                'path': 'api.py',
                'language': 'python',
                'symbol': 'upload_dataset',
                'content': 'def upload_dataset():\n    """Upload dataset to agent evaluator."""',
            },
        ]
    }
    result = retrieve(
        index,
        {},
        'Where is the dataset uploaded to the agent evaluator?',
        config=RetrievalConfig(mode='lexical', limit=1),
    )
    assert result[0]['chunk_id'] == 'z'
    assert {'agent', 'evaluator', 'dataset'} <= set(result[0]['ranking']['matched_terms'])
    assert result[0]['ranking']['lexical_mode'] == 'token_overlap'


def test_explicit_natural_identifier_anchor_retains_definition_priority():
    index = {
        'chunks': [
            {
                'id': 'a',
                'path': 'a.py',
                'symbol': 'upload_dataset_retry',
                'content': 'upload dataset',
            },
            {
                'id': 'z',
                'path': 'z.py',
                'language': 'python',
                'symbol': 'upload_dataset',
                'content': 'def upload_dataset(): pass',
            },
        ]
    }
    result = retrieve(
        index, {}, 'Where is upload_dataset defined?', config=RetrievalConfig(limit=1)
    )
    assert result[0]['chunk_id'] == 'z'
    assert result[0]['ranking']['anchor'] == 'upload_dataset'
    assert result[0]['ranking']['role'] == 'definition'


def test_stopword_only_natural_query_has_no_lexical_matches():
    result = retrieve({'chunks': [{'id': 'a', 'content': 'the where is'}]}, {}, 'where is the')
    assert result == []


def test_semantic_mode_requires_real_provider_and_lexical_skips_it():
    with pytest.raises(ValueError, match='Semantic mode requires'):
        search_hybrid({}, {}, 'question words', mode='semantic')

    class Forbidden:
        def embed_query(self, _query):
            pytest.fail('Lexical mode must not perform embedding inference')

    assert (
        search_hybrid(
            {}, {}, 'question words', mode='lexical', semantic_store=object(), provider=Forbidden()
        )
        == []
    )


def test_semantic_only_embeds_original_question_without_literal_results():
    class Provider:
        def embed_query(self, query):
            assert query == 'Where is the payload sent?'
            return [1.0]

    class Store:
        def search(self, _vector, **_kwargs):
            return [{'chunk_id': 'semantic', 'score': 0.8}]

    index = {
        'chunks': [
            {'id': 'literal', 'content': 'payload'},
            {'id': 'semantic', 'content': 'network dispatch'},
        ]
    }
    results = retrieve(
        index,
        {},
        'Where is the payload sent?',
        config=RetrievalConfig(mode='semantic'),
        semantic_store=Store(),
        provider=Provider(),
    )
    assert [row['chunk_id'] for row in results] == ['semantic']


def test_generation_receives_unmodified_natural_question():
    from coderag.generation import GenerationResult

    question = 'Where is upload_dataset defined?'

    class Provider:
        provider = 'ollama'

        def generate(self, prompt, *, metadata=None):  # noqa: ARG002 - provider protocol
            assert question in prompt
            return GenerationResult(
                'Definition found', 'ollama', 'test', citations=[{'chunk_id': 'a'}]
            )

    result = answer(
        question,
        index={
            'chunks': [
                {
                    'id': 'a',
                    'path': 'api.py',
                    'symbol': 'upload_dataset',
                    'language': 'python',
                    'content': 'def upload_dataset(): pass',
                    'start_line': 1,
                    'end_line': 1,
                },
            ]
        },
        graph={},
        generation_provider=Provider(),
    )
    assert result['answer'].answer == 'Definition found'


def test_query_cli_saves_original_plan_and_selected_sources(tmp_path):
    index, links, report = (tmp_path / name for name in ('index.json', 'links.json', 'report.json'))
    index.write_text(
        json.dumps(
            {
                'chunks': [
                    {
                        'id': 'a',
                        'path': 'api.py',
                        'symbol': 'upload_dataset',
                        'language': 'python',
                        'content': 'def upload_dataset(): pass',
                    },
                ]
            }
        )
    )
    links.write_text('{"evidence_graph": {"nodes": [], "edges": []}}')
    question = '¿Dónde está upload_dataset?'
    proc = subprocess.run(
        [
            sys.executable,
            '-m',
            'coderag',
            'query',
            question,
            '--index',
            str(index),
            '--relationships',
            str(links),
            '--retrieval-mode',
            'lexical',
            '--report',
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    plan = result['retrieval']['query_plan']
    assert plan['original_query'] == plan['routed_query'] == question
    assert plan['semantic_query'] == question
    assert plan['identifier_anchors'] == ['upload_dataset']
    assert 'semantic' not in plan['active_sources']
    assert json.loads(report.read_text())['metadata']['retrieval']['query_plan'] == plan


def test_inflection_variants_match_code_words_without_repetition_bonus():
    index = {
        'chunks': [
            {'id': 'noise', 'path': 'noise.py', 'symbol': 'uploaded', 'content': 'uploaded ' * 30},
            {'id': 'expected', 'path': 'api.py', 'symbol': 'upload_order', 'content': 'send order'},
        ]
    }
    plan = plan_query('How are orders uploaded?')
    assert 'upload' in plan['lexical_variants']['uploaded']
    assert 'order' in plan['lexical_variants']['orders']
    assert plan['semantic_query'] == 'How are orders uploaded?'
    result = retrieve(index, {}, plan['input'], config=RetrievalConfig(mode='lexical', limit=1))
    assert result[0]['chunk_id'] == 'expected'


def test_short_identifier_anchors_work_when_all_split_tokens_are_too_short():
    result = retrieve(
        {
            'chunks': [
                {
                    'id': 'x',
                    'path': 'a.py',
                    'symbol': '_x',
                    'language': 'python',
                    'content': 'def _x(): pass',
                }
            ]
        },
        {},
        'Where is _x?',
    )
    assert result[0]['chunk_id'] == 'x'
    assert result[0]['ranking']['anchor'] == '_x'


def test_lexical_pagination_does_not_require_semantic_artifact_files(tmp_path):
    index = tmp_path / 'indexes/demo.chunks.json'
    index.parent.mkdir()
    index.write_text(
        json.dumps(
            {
                'chunks': [
                    {'id': str(n), 'path': f'{n}.py', 'content': 'send order'} for n in range(2)
                ]
            }
        )
    )
    (index.parent / 'demo.relationships.json').write_text(
        '{"evidence_graph": {"nodes": [], "edges": []}}'
    )
    config = tmp_path / 'config.json'
    config.write_text(
        json.dumps({'repositories': {'demo': {}}, 'retrieval': {'semantic_enabled': True}})
    )
    proc = subprocess.run(
        [
            sys.executable,
            '-m',
            'coderag',
            'query',
            'Where is an order sent?',
            '--config',
            str(config),
            '--default-repo',
            'demo',
            '--retrieval-mode',
            'lexical',
            '--page-size',
            '1',
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)['pagination']['next_cursor']


def test_backtick_identifiers_are_not_lost_as_stopwords():
    plan = plan_query('Where is `es` defined?')
    assert plan['identifier_anchors'] == ['es']
    results = retrieve(
        {
            'chunks': [
                {
                    'id': 'a',
                    'path': 'a.py',
                    'symbol': 'es',
                    'language': 'python',
                    'content': 'def es(): pass',
                }
            ]
        },
        {},
        plan['input'],
    )
    assert results[0]['ranking']['anchor'] == 'es'


def test_term_coverage_beats_an_isolated_rare_symbol_before_top_k():
    index = {
        'chunks': [
            {'id': 'noise', 'path': 'noise.py', 'symbol': 'cancellation', 'content': ''},
            *[{'id': str(i), 'path': f'file{i}.py', 'content': 'handoff tools'} for i in range(20)],
        ]
    }
    result = retrieve(
        index,
        {},
        'Which tools implement handoff cancellation?',
        config=RetrievalConfig(mode='lexical', limit=1),
    )
    assert result[0]['chunk_id'] != 'noise'
    assert {'handoff', 'tools'} <= set(result[0]['ranking']['matched_terms'])
    assert result[0]['ranking']['term_coverage'] == 0.5


def test_high_semantic_similarity_cannot_displace_broader_literal_coverage_in_hybrid():
    class Provider:
        def embed_query(self, _query):
            return [1.0]

    class Store:
        def search(self, _vector, **_kwargs):
            return [{'chunk_id': 'noise', 'score': 1.0}]

    index = {
        'chunks': [
            {'id': 'noise', 'path': 'mkdocs.yml', 'content': 'repo_name: unrelated'},
            {'id': 'tool', 'path': 'tools.py', 'content': 'handoff'},
        ]
    }
    result = retrieve(
        index,
        {},
        'Which tools implement handoff?',
        config=RetrievalConfig(limit=1),
        semantic_store=Store(),
        provider=Provider(),
    )
    assert result[0]['chunk_id'] == 'tool'
    assert result[0]['ranking']['term_coverage'] == pytest.approx(2 / 3)


def test_semantic_only_retains_similarity_order_without_literal_coverage_bias():
    class Provider:
        def embed_query(self, _query):
            return [1.0]

    class Store:
        def search(self, _vector, **_kwargs):
            return [{'chunk_id': 'synonym', 'score': 0.9}, {'chunk_id': 'literal', 'score': 0.8}]

    results = retrieve(
        {
            'chunks': [
                {'id': 'synonym', 'content': 'escalate request'},
                {'id': 'literal', 'content': 'handoff tools'},
            ]
        },
        {},
        'Which tools implement handoff?',
        config=RetrievalConfig(mode='semantic'),
        semantic_store=Store(),
        provider=Provider(),
    )
    assert [row['chunk_id'] for row in results] == ['synonym', 'literal']
