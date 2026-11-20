"""Exercise the resident MLX worker using a lightweight local runtime."""

import json
import os
from pathlib import Path

import pytest

from codetrace.chat import ChatApplication, ChatError


def test_chat_reuses_mlx_and_restarts_after_timeout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    source = Path(__file__).resolve().parents[1] / 'src'
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join((str(tmp_path), str(source))))
    monkeypatch.setenv('CODETRACE_GENERATION_PROVIDER', 'mlx')
    monkeypatch.setenv('CODETRACE_GENERATION_MODEL', str(tmp_path))
    monkeypatch.setenv('CHAT_LANG', 'es')
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'repositories': {'demo': {}}}), encoding='utf-8')
    indexes = tmp_path / 'indexes'
    indexes.mkdir()
    (indexes / 'demo.chunks.json').write_text('{"chunks": []}', encoding='utf-8')
    (indexes / 'demo.relationships.json').write_text('{"evidence_graph": {}}', encoding='utf-8')
    marker = tmp_path / 'loads'
    (tmp_path / 'mlx_lm.py').write_text(
        """
from pathlib import Path
from time import sleep
from types import SimpleNamespace

def load(path):
    with (Path(path) / 'loads').open('a') as marker:
        marker.write('load\\n')
    return object(), SimpleNamespace(chat_template=None)

def generate(_model, _tokenizer, *, prompt, **_options):
    if 'force runtime timeout' in prompt:
        sleep(30)
    return '{"answer":"ok","claims":[],"citations":[]}'
""",
        encoding='utf-8',
    )

    application = ChatApplication(config, timeout=7)
    try:
        first = application.answer(
            {'question': 'What is indexed?', 'repo': 'demo', 'session': 'new'}
        )
        application.answer({'question': 'Again?', 'repo': 'demo', 'session': first['session']})
        assert marker.read_text(encoding='utf-8').splitlines() == ['load']

        application.timeout = 0.2
        with pytest.raises(ChatError, match='tiempo') as error:
            application.answer({'question': 'force runtime timeout', 'repo': 'demo'})
        assert error.value.status == 504

        application.timeout = 7
        output = application.answer({'question': 'After timeout?', 'repo': 'demo'})
        assert output['answer']['answer'] == 'ok'
        assert marker.read_text(encoding='utf-8').splitlines() == ['load', 'load']
    finally:
        application.close()

    baseline = ChatApplication(config, timeout=7, reuse_mlx=False)
    try:
        assert (
            baseline.answer({'question': 'Baseline?', 'repo': 'demo'})['answer']['answer'] == 'ok'
        )
    finally:
        baseline.close()

    history = indexes / 'reports' / 'requests.jsonl'
    events = [json.loads(line) for line in history.read_text(encoding='utf-8').splitlines()]
    pipeline = [event['timings'] for event in events if event['source'] == 'chat']
    assert len(pipeline) == 4
    assert 'mlx_model_load_seconds' in pipeline[0]
    assert 'mlx_model_load_seconds' not in pipeline[1]
    assert 'mlx_model_load_seconds' in pipeline[2]
    assert 'mlx_model_load_seconds' in pipeline[3]
    assert all('mlx_inference_seconds' in timings for timings in pipeline)
    assert [
        (event['source'], event['status']) for event in events if event['source'] != 'chat'
    ] == [
        ('chat_request_persistent', 'ok'),
        ('chat_request_persistent', 'ok'),
        ('chat_request_persistent', 'error'),
        ('chat_request_persistent', 'ok'),
        ('chat_request_subprocess', 'ok'),
    ]
