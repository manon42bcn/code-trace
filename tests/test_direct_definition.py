import json

import pytest

from codetrace.generation import GenerationResult
from codetrace.rag_pipeline import answer
from codetrace.sqlite_index import open_sqlite_index, prepare_sqlite_index


@pytest.fixture
def index():
    step = 'a signed form exists'
    return {
        'chunks': [
            {
                'id': 'a',
                'symbol': 'submit_form',
                'language': 'python',
                'path': 'service/forms.py',
                'start_line': 8,
                'end_line': 10,
                'content': '@given("a signed form exists")\ndef submit_form():\n    pass',
            },
            {
                'id': 'b',
                'symbol': 'other',
                'path': 'service/consumer.py',
                'start_line': 2,
                'end_line': 2,
                'content': 'submit_form()',
            },
        ],
        'behave_relations': {
            'step_definitions': [{'chunk_id': 'a', 'keyword': 'given', 'pattern': step}]
        },
    }


class Provider:
    provider = 'ollama'
    model = 'test'

    def __init__(self):
        self.calls = 0

    def generate(self, _prompt, **_kwargs):
        self.calls += 1
        return GenerationResult('modelo', self.provider, self.model)


@pytest.mark.parametrize(
    ('question', 'previous'),
    [
        ('¿Dónde se define `submit_form`?', None),
        ('Where is submit_form defined?', None),
        ('¿Dónde se define el step `Given a signed form exists`?', None),
        ('¿Dónde se define ese step?', 'Usa `Given a signed form exists`.'),
        ('Where is that function defined?', 'Use `submit_form`.'),
    ],
)
@pytest.mark.parametrize('sqlite', [False, True])
def test_direct_definition_uses_unique_evidence(index, question, previous, sqlite, tmp_path):
    from contextlib import nullcontext

    if sqlite:
        path = tmp_path / 'index.json'
        path.write_text(json.dumps(index), encoding='utf-8')
        prepare_sqlite_index(path)
    provider = Provider()
    with open_sqlite_index(path) if sqlite else nullcontext(index) as snapshot:
        result = answer(
            question,
            index=snapshot,
            graph={},
            generation_provider=provider,
            history=[{'answer': previous}] if previous is not None else None,
            prefer_direct=True,
        )
    assert provider.calls == 0
    assert result['answer_mode'] == 'direct_definition'
    assert not result['generated']
    assert result['answer'].citations[0]['chunk_id'] == 'a'
    assert 'service/forms.py:8-10' in result['answer'].answer
    assert 'def submit_form()' in result['context']['items'][0]['content']


@pytest.mark.parametrize(
    ('question', 'previous'),
    [
        ('¿Qué step envía el formulario?', None),
        ('¿Y si quiero enviarlo inline?', 'Usa `submit_form`.'),
        ('¿Dónde se usa submit_form?', None),
        ('¿Dónde se define `submit_form` y qué hace?', None),
        ('¿Dónde se define ese step?', 'Usa `submit_form` o `submit_other`.'),
        ('¿Dónde se define missing?', None),
    ],
)
def test_ambiguous_or_explanatory_questions_keep_generation(index, question, previous):
    provider = Provider()
    result = answer(
        question,
        index=index,
        graph={},
        generation_provider=provider,
        history=[{'question': 'previa', 'answer': previous}] if previous else None,
        prefer_direct=True,
    )
    assert provider.calls == 1
    assert result['generated']
    assert result.get('answer_mode') is None


def test_multiple_definitions_keep_generation(index):
    index['chunks'].append({**index['chunks'][0], 'id': 'c', 'path': 'other/forms.py'})
    provider = Provider()
    result = answer(
        'Where is submit_form defined?',
        index=index,
        graph={},
        generation_provider=provider,
        prefer_direct=True,
    )
    assert result['generated']
    assert provider.calls == 1
