"""Request-flow questions must surface handlers and calls with bounded static claims."""

import pytest

from coderag.code_flow import flow_candidates, is_flow_query
from coderag.core import build_chunks
from coderag.evidence_graph import build_evidence_graph
from coderag.grounded_prompt import build_grounded_prompt
from coderag.intent_context import build_context_for_query
from coderag.rag_pipeline import answer

SETTINGS = {
    'chunking': {
        'max_tokens': 1024,
        'overlap_tokens': 0,
        'on_missing_parser': 'error',
        'preserve_symbols': True,
        'include_parent_context': True,
    }
}
SOURCE = """from fastapi import FastAPI
app = FastAPI()

@app.post('/orders')
async def create_order():
    return save_order()

def save_order():
    return validate_order()

def validate_order():
    return True

@app.get('/health')
def health():
    return 'ok'
"""


def flow_context(*args, **kwargs):
    return build_context_for_query(*args, flow_analysis=True, **kwargs)


@pytest.fixture
def prepared():
    chunks = build_chunks('app.py', 'python', SOURCE, SETTINGS)
    # Configuration noise must never become the entry point.
    chunks.append(
        {'id': 'noise', 'path': 'meta.yaml', 'language': 'yaml', 'content': 'request: first'}
    )
    index = {'chunks': chunks}
    graph = build_evidence_graph({'demo': index}, {'relations': [], 'source_repository': 'demo'})
    ids = {c['symbol']: c['id'] for c in chunks if c.get('symbol')}
    return index, graph, ids


@pytest.mark.parametrize(
    'query',
    [
        '¿Cuál es la primera función al llegar una petición?',
        'Cuál es el flujo de POST /orders',
        'Explain the request flow',
        'Which function handles the request?',
        'Show the flow from save_order',
    ],
)
def test_detect_flow_questions(query):
    assert is_flow_query(query)


@pytest.mark.parametrize(
    'query', ['cuántas tools hay', 'save_order', 'Dónde se configura el modelo']
)
def test_regular_queries_are_unchanged(query):
    assert not is_flow_query(query)


def test_http_endpoint_prioritizes_handler_and_local_calls_over_yaml_noise(prepared):
    index, graph, ids = prepared
    context = flow_context(
        index, graph, 'Flujo de la petición POST /orders', [{'chunk_id': 'noise'}], max_chunks=3
    )
    assert [i['citation']['chunk_id'] for i in context['items']] == [
        ids['create_order'],
        ids['save_order'],
        ids['validate_order'],
    ]
    flow = context['code_flow']
    assert flow['matching_entry_candidates'] == 1
    assert flow['recognized_http_candidates'] == 2
    assert not flow['ambiguous_entry']
    assert flow['entries'][0]['route'] == '/orders'
    assert len(flow['edges']) == 2
    assert all(not e['runtime_verified'] for e in flow['edges'])
    prompt = build_grounded_prompt(context['query'], context)
    assert 'Do not assert a globally first function' in prompt
    assert 'middleware' in prompt
    assert 'create_order' in prompt


def test_generic_request_marks_multiple_entries_without_picking_a_global_first(prepared):
    index, graph, ids = prepared
    context = flow_context(index, graph, 'Primera función al llegar una petición', [], max_chunks=2)
    flow = context['code_flow']
    assert flow['ambiguous_entry']
    assert flow['matching_entry_candidates'] == 2
    assert {e['chunk_id'] for e in flow['entries']} == {ids['create_order'], ids['health']}
    assert not flow['edges']
    assert context['selection']['excluded_by_budget']['max_chunks'] == 2


def test_budgeted_context_never_exposes_unsupplied_call_targets(prepared):
    index, graph, ids = prepared
    context = flow_context(index, graph, 'Request flow POST /orders', [], max_chunks=1)
    assert context['items'][0]['citation']['chunk_id'] == ids['create_order']
    assert context['code_flow']['edges'] == []
    assert context['code_flow']['candidate_nodes'] == 3
    assert ids['save_order'] not in str(context['code_flow'])


def test_no_matching_route_does_not_invent_an_entry(prepared):
    index, graph, _ = prepared
    context = flow_context(index, graph, 'Request flow DELETE /missing', [])
    assert context['code_flow']['matching_entry_candidates'] == 0
    assert not context['code_flow']['entries']
    assert 'cannot identify the entry point' in build_grounded_prompt(context['query'], context)


def test_symbol_flow_uses_existing_call_edges(prepared):
    index, graph, ids = prepared
    context = flow_context(
        index, graph, 'Flujo desde save_order', [{'chunk_id': ids['save_order']}]
    )
    assert context['code_flow']['entries'][0]['symbol'] == 'save_order'
    assert context['code_flow']['edges'][0]['target'] == ids['validate_order']


def test_imported_router_aliases_and_flask_method_lists():
    sources = {
        'routing.py': 'from fastapi import APIRouter\nrouter = APIRouter()\n',
        'handlers.py': (
            "from routing import router as api\n@api.get('/items')\ndef items():\n    pass\n"
        ),
        'flask_app.py': (
            'from flask import Flask\napp = Flask(__name__)\n'
            "@app.route('/x', methods=['POST'])\ndef handler():\n    pass\n"
        ),
        'unrelated.py': "cache = object()\n@cache.get('/not-http')\ndef cached():\n    pass\n",
    }
    index = {
        'chunks': [
            c
            for path, source in sources.items()
            for c in build_chunks(path, 'python', source, SETTINGS)
        ]
    }
    _, flow = flow_candidates(index, {}, 'Request flow', [])
    assert {e['route'] for e in flow['entries']} == {'/items', '/x'}
    assert flow['matching_entry_candidates'] == 2
    _, flow = flow_candidates(index, {}, 'Request flow POST /x', [])
    assert flow['entries'][0]['symbol'] == 'handler'


def test_depth_and_node_bounds(prepared):
    index, graph, _ids = prepared
    _, flow = flow_candidates(index, graph, 'Request flow POST /orders', [], max_depth=1)
    assert flow['traversal_truncated']
    assert flow['candidate_nodes'] == 2
    _, flow = flow_candidates(index, graph, 'Request flow POST /orders', [], max_nodes=1)
    assert flow['traversal_truncated']
    assert flow['candidate_nodes'] == 1
    assert not flow['edges']


def test_answer_pipeline_receives_flow_without_bypassing_generation_validation(prepared):
    from coderag.generation import Claim, GenerationResult

    index, graph, ids = prepared

    class Provider:
        provider = 'ollama'

        def generate(self, prompt, *, metadata=None):  # noqa: ARG002 - Provider protocol
            assert 'Static flow metadata' in prompt
            assert 'create_order' in prompt
            return GenerationResult(
                'El handler candidato es create_order.',
                'ollama',
                'test',
                claims=[Claim('Handler candidato', 'static_candidate', [ids['create_order']])],
                citations=[{'chunk_id': ids['create_order']}],
            )

    result = answer(
        'Flujo de la petición POST /orders',
        index=index,
        graph=graph,
        retrieval_results=[{'chunk_id': 'noise'}],
        generation_provider=Provider(),
        context_limits={'max_chunks': 3},
    )
    assert result['generated']
    assert result['answer'].answer == 'El handler candidato es create_order.'
    assert result['context']['code_flow']['edges']


def test_http_method_question_without_request_keyword(prepared):
    index, graph, _ids = prepared
    context = flow_context(index, graph, 'Cuál es el flujo de POST /orders', [])
    assert context['code_flow']['matching_entry_candidates'] == 1
    assert context['code_flow']['entries'][0]['symbol'] == 'create_order'


def test_explicit_symbol_does_not_require_a_lexical_match(prepared):
    index, graph, _ids = prepared
    context = flow_context(index, graph, 'Show the flow from save_order', [{'chunk_id': 'noise'}])
    assert context['code_flow']['entries'][0]['symbol'] == 'save_order'
    context = flow_context(index, graph, 'Show the flow from missing_function', [])
    assert context['code_flow']['matching_entry_candidates'] == 0


def test_evidence_only_context_does_not_change_pagination_candidates(prepared):
    index, graph, _ids = prepared
    context = build_context_for_query(
        index, graph, 'Request flow POST /orders', [{'chunk_id': 'noise'}]
    )
    assert 'code_flow' not in context
    assert context['items'][0]['citation']['chunk_id'] == 'noise'


def test_markdown_answer_shows_bounded_flow_without_changing_provider_text(prepared):
    from coderag.answer_display import render_answer
    from coderag.generation import GenerationResult

    index, graph, _ids = prepared
    context = flow_context(index, graph, 'Request flow POST /orders', [], max_chunks=2)
    generated = GenerationResult('Respuesta literal\n', 'ollama', 'test')
    result = {'answer': generated, 'context': context}
    assert render_answer(result) == generated.answer
    text = render_answer(result, include_evidence=True, markdown=True)
    assert '## Flujo estático' in text
    assert 'create_order' in text
    assert 'save_order' in text
    assert 'no representan el orden de ejecución' in text


def test_call_cycles_terminate_with_deterministic_evidence(prepared):
    index, graph, ids = prepared
    symbols = {n['chunk_id']: n['id'] for n in graph['nodes'] if n['kind'] == 'python_symbol'}
    graph['edges'].append(
        {
            'source': symbols[ids['validate_order']],
            'target': symbols[ids['create_order']],
            'type': 'calls',
            'evidence': 'static_unique_call_target',
        }
    )
    _, flow = flow_candidates(index, graph, 'Request flow POST /orders', [])
    assert flow['candidate_nodes'] == 3
    assert len(flow['edges']) == 3


def test_flow_respects_token_budget(prepared):
    index, graph, _ids = prepared
    context = flow_context(index, graph, 'Request flow POST /orders', [], max_tokens=1)
    assert context['estimated_tokens'] <= 1
    assert not context['code_flow']['entries']
    assert not context['code_flow']['edges']


def test_relative_router_reexport_from_package_init():
    sources = {
        'pkg/routing.py': 'from fastapi import APIRouter\nrouter = APIRouter()\n',
        'pkg/__init__.py': 'from .routing import router\n',
        'pkg/handlers.py': (
            "from . import router as api\n@api.get('/relative')\ndef handler():\n    pass\n"
        ),
    }
    index = {
        'chunks': [
            c
            for path, source in sources.items()
            for c in build_chunks(path, 'python', source, SETTINGS)
        ]
    }
    _, flow = flow_candidates(index, {}, 'Request flow GET /relative', [])
    assert flow['entries'][0]['symbol'] == 'handler'


def test_node_bound_also_limits_multiple_roots(prepared):
    index, graph, _ids = prepared
    _, flow = flow_candidates(index, graph, 'Request flow', [], max_nodes=1)
    assert flow['candidate_nodes'] == 1
    assert flow['traversal_truncated']
