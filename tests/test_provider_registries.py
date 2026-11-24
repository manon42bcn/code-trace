import json

from codetrace.embeddings import EmbeddingMetadata
from codetrace.generation_config import load_generation_config
from codetrace.generation_factory import build_generation_provider
from codetrace.generation_safety import is_local_generation_provider
from codetrace.providers.embeddings.metrics import embed_documents, embed_query
from codetrace.providers.embeddings.registry import (
    EMBEDDING_PROVIDERS,
    EmbeddingRegistration,
    embedding_runtime_issue,
)
from codetrace.providers.llm.registry import GENERATION_PROVIDERS, GenerationRegistration
from codetrace.request_metrics import request_metrics
from codetrace.semantic_config import resolve_retrieval


def test_registered_llm_is_selected_from_configuration(monkeypatch):
    class Example:
        provider = 'example'

        def __init__(self, config):
            self.model = config.model

        def generate(self, _prompt, **_kwargs):
            raise AssertionError('This test does not call a model')

    monkeypatch.setitem(
        GENERATION_PROVIDERS,
        'example',
        GenerationRegistration(Example, requires_model=True, execution='local'),
    )
    monkeypatch.setenv('CODETRACE_GENERATION_PROVIDER', 'example')
    monkeypatch.setenv('CODETRACE_GENERATION_MODEL', 'example-model')
    provider = build_generation_provider(load_generation_config())

    assert isinstance(provider, Example)
    assert provider.model == 'example-model'
    assert is_local_generation_provider(provider)


def test_registered_embedding_adapter_resolves_paths_and_logs_usage(tmp_path, monkeypatch):
    class Example:
        def __init__(self, model):
            self.metadata = EmbeddingMetadata(model, 2, 'v1')

        def embed_documents(self, texts):
            return [self.embed_query(text) for text in texts]

        def embed_query(self, _text):
            return [1, 0]

    monkeypatch.setitem(
        EMBEDDING_PROVIDERS,
        'example',
        EmbeddingRegistration(
            Example, lambda _: None, lambda _, model: model, 'example:', '.example'
        ),
    )
    monkeypatch.setenv('CODETRACE_EMBEDDING_PROVIDER', 'example')
    monkeypatch.setenv('CODETRACE_EMBEDDING_MODEL', 'local-model')
    _, paths, model = resolve_retrieval({}, tmp_path / 'config.json', tmp_path / 'index.json')
    assert model == 'example:local-model'
    assert paths['v1'].name == 'index.vectors-v1.example.json'
    assert embedding_runtime_issue(model) is None

    from codetrace.embedding_provider import build_embedding_provider

    provider = build_embedding_provider(model)
    assert isinstance(provider, Example)
    with request_metrics('answer', 'example', 'generative-model'):
        assert embed_query(provider, 'private query') == [1, 0]
        assert embed_documents(provider, ['private code']) == [[1, 0]]

    history = (tmp_path / 'indexes/reports/requests.jsonl').read_text()
    events = [json.loads(line) for line in history.splitlines()]
    assert [event['source'] for event in events] == ['embedding_query', 'embedding_index', 'answer']
    assert events[0]['provider'] == 'example'
    assert events[0]['model'] == model
    assert events[1]['input_count'] == 1
    assert 'private' not in history
