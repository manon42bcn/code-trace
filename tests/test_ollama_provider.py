import json
from io import BytesIO

from coderag.ollama_provider import OllamaProvider


def test_ollama_provider_parses_structured_response(monkeypatch):
    payload = {
        'response': json.dumps({'answer': 'ok', 'claims': [], 'citations': [], 'limitations': []})
    }

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        'coderag.ollama_provider.urlopen',
        lambda _request, timeout: Response(json.dumps(payload).encode()),  # noqa: ARG005 - urlopen keyword
    )
    result = OllamaProvider(model='local').generate('prompt')
    assert result.answer == 'ok'
    assert result.provider == 'ollama'
