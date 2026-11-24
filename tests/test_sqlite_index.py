import json
from contextvars import Context
from types import SimpleNamespace

import pytest

from codetrace.__main__ import main
from codetrace.chat import ChatApplication
from codetrace.generation import GenerationResult
from codetrace.lexical_search import search_index
from codetrace.query_planning import plan_query
from codetrace.sqlite_index import open_sqlite_index, prepare_sqlite_index


@pytest.fixture
def snapshot(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text('{"repositories":{"demo":{}}}', encoding='utf-8')
    indexes = tmp_path / 'indexes'
    indexes.mkdir()
    index_path = indexes / 'demo.chunks.json'
    index = {
        'chunks': [
            {
                'id': 'a',
                'path': 'agents_factory.py',
                'start_line': 1,
                'end_line': 2,
                'symbol': 'create_agent',
                'language': 'python',
                'content': 'def create_agent(id):\n    return id',
            },
            {
                'id': 'b',
                'path': 'consumer.py',
                'start_line': 3,
                'end_line': 3,
                'content': 'agent = create_agent(id)',
            },
            {
                'id': 'c',
                'path': 'other.py',
                'start_line': 1,
                'end_line': 1,
                'symbol': None,
                'content': 'before\0after',
            },
        ],
    }
    index_path.write_text(json.dumps(index), encoding='utf-8')
    graph = {
        'nodes': [
            {'id': 'node-a', 'chunk_id': 'a', 'symbol': 'create_agent'},
            {'id': 'node-c', 'chunk_id': 'c'},
        ],
        'edges': [{'source': 'node-a', 'target': 'node-c', 'type': 'calls'}],
    }
    (indexes / 'demo.relationships.json').write_text(
        json.dumps({'evidence_graph': graph}), encoding='utf-8'
    )
    return config, index_path, index


def test_sqlite_preserves_rank_and_explicit_snapshot(snapshot):
    _config, path, original = snapshot
    prepare_sqlite_index(path)

    with open_sqlite_index(path) as index:
        for question in (
            'create_agent',
            'id',
            'agents_factory.py',
            'after',
            '¿Dónde se crea un agente?',
        ):
            plan = plan_query(question)
            assert search_index(index, question, query_plan=plan) == search_index(
                original, question, query_plan=plan
            )
        assert list(index['chunks']) == original['chunks']
        path.write_text('{"chunks": []}', encoding='utf-8')
        prepare_sqlite_index(path)
        assert len(index['chunks']) == len(original['chunks'])

    with open_sqlite_index(path) as rebuilt:
        assert len(rebuilt['chunks']) == 0


def test_sqlite_chat_preserves_evidence_and_graph_expansion(snapshot, monkeypatch, capsys):
    config, path, _ = snapshot
    monkeypatch.setenv('CODETRACE_GENERATION_PROVIDER', 'ollama')
    monkeypatch.setenv('CODETRACE_GENERATION_MODEL', 'test')

    calls = []

    class Provider:
        provider = 'ollama'
        model = 'test'

        def generate(self, _prompt, **_kwargs):
            calls.append(_prompt)
            return GenerationResult('ok', self.provider, self.model)

    def run(command, **_kwargs):
        code = Context().run(main, command[3:])
        return SimpleNamespace(returncode=code, stdout=capsys.readouterr().out)

    monkeypatch.setattr(
        'codetrace.generation_factory.build_generation_provider', lambda _: Provider()
    )
    monkeypatch.setattr('codetrace.chat.subprocess.run', run)
    payload = {'question': 'create_agent', 'repo': 'demo'}
    baseline = ChatApplication(config, reuse_mlx=False).answer(payload)
    main(['prepare-sqlite', str(path)])
    capsys.readouterr()
    application = ChatApplication(config, reuse_mlx=False)
    experimental = application.answer(payload)

    assert baseline['index_backend'] == 'json'
    assert experimental['index_backend'] == 'sqlite'
    assert experimental['context'] == baseline['context']
    assert [item['citation']['chunk_id'] for item in experimental['context']['items']] == [
        'a',
        'b',
        'c',
    ]

    direct = application.answer({'question': 'Where is create_agent defined?', 'repo': 'demo'})
    assert direct['answer_mode'] == 'direct_definition'
    assert direct['answer']['citations'][0]['chunk_id'] == 'a'
    assert len(calls) == 2
