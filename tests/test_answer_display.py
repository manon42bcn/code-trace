"""Answers are relayed verbatim; evidence formatting never uses another model."""

import json
import sys

import pytest

from coderag import __main__ as cli, generation_factory
from coderag.answer_display import render_answer
from coderag.generation import Claim, GenerationResult

ANSWER = 'Respuesta **literal**: sí.\nNo cambiar «este texto».\n'


def result():
    return {
        'answer': GenerationResult(ANSWER, 'ollama', 'test', citations=[{'chunk_id': 'a'}]),
        'context': {
            'items': [
                {
                    'chunk': {'language': 'yaml'},
                    'citation': {
                        'chunk_id': 'a',
                        'path': 'agent.yaml',
                        'start_line': 2,
                        'end_line': 4,
                        'symbol': '$/agent/tools/0',
                    },
                    'content': 'tool_name: alpha\n```\noriginal',
                    'certainty': 'static_candidate',
                    'content_truncated': False,
                    'limitations': ['Static evidence only.'],
                },
                {
                    'chunk': {'language': 'json'},
                    'citation': {
                        'chunk_id': 'b',
                        'path': 'config.json',
                        'start_line': 1,
                        'end_line': 10,
                    },
                    'content': '{"enabled": true}',
                    'content_truncated': True,
                    'certainty': 'static_candidate',
                    'limitations': ['Static evidence only.'],
                },
            ]
        },
    }


def test_answer_only_is_identical_including_whitespace():
    assert render_answer(result()) == ANSWER


def test_evidence_is_appended_with_original_content_citations_and_limitations():
    rendered = render_answer(result(), include_evidence=True, repository='demo')
    assert rendered.startswith(ANSWER)
    assert 'agent.yaml: 2-4' in rendered
    assert 'Símbolo: $/agent/tools/0' in rendered
    assert 'Citada en la respuesta' in rendered
    assert 'Contexto recuperado; sin cita en la respuesta' in rendered
    assert 'Fragmento truncado' in rendered
    assert rendered.count('Static evidence only.') == 1
    assert '````yaml\ntool_name: alpha\n```\noriginal\n````' in rendered


def test_no_evidence_leaves_answer_unchanged():
    payload = result()
    payload['context']['items'] = []
    assert render_answer(payload, include_evidence=True) == ANSWER


@pytest.fixture
def configured(tmp_path):
    (tmp_path / 'indexes').mkdir()
    (tmp_path / 'indexes/demo.chunks.json').write_text(
        json.dumps(
            {
                'chunks': [
                    {
                        'id': 'a',
                        'path': 'a.py',
                        'start_line': 1,
                        'end_line': 1,
                        'content': 'order_id = 1',
                        'language': 'python',
                    }
                ]
            }
        )
    )
    (tmp_path / 'indexes/demo.relationships.json').write_text(json.dumps({'evidence_graph': {}}))
    path = tmp_path / 'config.json'
    path.write_text(
        json.dumps(
            {'repositories': {'demo': {}}, 'generation': {'provider': 'ollama', 'model': 'test'}}
        )
    )
    return path


@pytest.mark.parametrize('evidence', [False, True])
@pytest.mark.parametrize('output_format', ['text', 'markdown'])
def test_answer_cli_routing_reports_and_verbatim_text(
    configured, monkeypatch, capsys, evidence, output_format
):
    class Provider:
        provider = 'ollama'

        def generate(self, prompt, *, metadata=None):  # noqa: ARG002 - Provider protocol keyword
            assert 'order_id' in prompt
            print('provider diagnostic')  # noqa: T201 - Test stderr redirection
            return GenerationResult(
                ANSWER,
                'ollama',
                'test',
                claims=[Claim('fact', 'static_candidate', ['a'])],
                citations=[{'chunk_id': 'a'}],
            )

    monkeypatch.setattr(generation_factory, 'build_generation_provider', lambda _config: Provider())
    report = configured.parent / 'report.json'
    argv = [
        'coderag',
        'answer',
        'En demo, order_id',
        '--default-repo',
        'demo',
        '--config',
        str(configured),
        '--output-format',
        output_format,
        '--report',
        str(report),
    ]
    if evidence:
        argv.append('--include-evidence')
    monkeypatch.setattr(sys, 'argv', argv)
    cli.main()
    captured = capsys.readouterr()
    assert ANSWER in captured.out
    if output_format == 'markdown':
        body = captured.out.split('## Respuesta\n\n', 1)[1]
        assert body.split('\n\n## Fuentes', 1)[0] == ANSWER
    else:
        assert captured.out.startswith(ANSWER)
    assert 'provider diagnostic' in captured.err
    if evidence:
        assert 'a.py: 1-1' in captured.out
        assert 'order_id = 1' in captured.out
    elif output_format == 'text':
        assert captured.out == ANSWER
    saved = json.loads(report.read_text())
    assert saved['answer']['answer'] == ANSWER
    assert saved['metadata']['routing']['repository'] == 'demo'


def test_text_output_without_provider_fails_instead_of_synthesizing(
    configured, monkeypatch, capsys
):
    data = json.loads(configured.read_text())
    data['generation']['provider'] = 'none'
    configured.write_text(json.dumps(data))
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'coderag',
            'answer',
            'order_id',
            '--default-repo',
            'demo',
            '--config',
            str(configured),
            '--output-format',
            'text',
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert (
        'configured generation provider' in json.loads(capsys.readouterr().out)['error']['message']
    )


def test_markdown_layout_preserves_answer_and_every_source_excerpt():
    payload = result()
    rendered = render_answer(payload, include_evidence=True, repository='demo', markdown=True)
    assert '**Repositorio:**' in rendered
    assert '**Proveedor:**' in rendered
    assert '**Modelo:**' in rendered
    assert '| Fuente | Archivo y líneas | Uso | Certeza |' in rendered
    assert '| Citada |' in rendered
    assert '| Solo contexto |' in rendered
    assert '## Fragmentos de evidencia' in rendered
    assert '### Fuente 1' in rendered
    assert '## Limitaciones' in rendered
    assert rendered.split('## Respuesta\n\n', 1)[1].split('\n\n## Fuentes', 1)[0] == ANSWER
    for item in payload['context']['items']:
        assert item['content'] in rendered


def test_markdown_metadata_cannot_add_extra_table_columns():
    payload = result()
    payload['context']['items'][0]['citation']['path'] = 'a|b`file.yaml'
    rendered = render_answer(payload, include_evidence=True, markdown=True)
    assert r'a\|b`file.yaml' in rendered
    assert '`` a' in rendered


@pytest.mark.parametrize('explicit_flag', [False, True])
def test_answer_cli_sends_handoff_evidence_without_repository_metadata_to_provider(
    configured, monkeypatch, capsys, explicit_flag
):
    index = configured.parent / 'indexes/demo.chunks.json'
    index.write_text(
        json.dumps(
            {
                'chunks': [
                    {
                        'id': 'repo-url',
                        'path': 'mkdocs.yml',
                        'symbol': '$/repo_url',
                        'content': 'repo_url: https://example.test/repo',
                        'start_line': 1,
                        'end_line': 1,
                    },
                    {
                        'id': 'repo-name',
                        'path': 'mkdocs.yml',
                        'symbol': '$/repo_name',
                        'content': 'repo_name: demo',
                        'start_line': 2,
                        'end_line': 2,
                    },
                    {
                        'id': 'handoff',
                        'path': 'tools/handoff.py',
                        'symbol': 'make_handoff_tool',
                        'content': 'def make_handoff_tool(): return human_handoff',
                        'language': 'python',
                        'start_line': 1,
                        'end_line': 1,
                    },
                ]
            }
        )
    )

    class Provider:
        provider = 'ollama'

        def generate(self, prompt, *, metadata=None):  # noqa: ARG002 - Provider protocol
            question = prompt.split('Question:\n', 1)[1].split('\n\nEvidence:', 1)[0]
            assert 'demo' not in question
            assert '--repo' not in question
            assert 'make_handoff_tool' in prompt
            assert 'repo_url' not in prompt
            assert 'repo_name' not in prompt
            return GenerationResult(
                'Existe una tool de handoff.', 'ollama', 'test', citations=[{'chunk_id': 'handoff'}]
            )

    monkeypatch.setattr(generation_factory, 'build_generation_provider', lambda _cfg: Provider())
    question = '¿Qué tools incluyen handoff en demo?'
    argv = [
        'coderag',
        'answer',
        question if explicit_flag else question + ' --repo demo',
        '--config',
        str(configured),
        '--default-repo',
        'demo',
    ]
    if explicit_flag:
        argv += ['--repo', 'demo']
    monkeypatch.setattr(sys, 'argv', argv)
    cli.main()
    data = json.loads(capsys.readouterr().out)
    assert data['answer']['answer'] == 'Existe una tool de handoff.'
    assert [item['citation']['chunk_id'] for item in data['context']['items']] == ['handoff']


def test_answer_unknown_explicit_repository_fails_before_loading_models(
    configured, monkeypatch, capsys
):
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'coderag',
            'answer',
            'handoff tools',
            '--config',
            str(configured),
            '--repo',
            'missing',
        ],
    )
    monkeypatch.setattr(
        generation_factory,
        'build_generation_provider',
        lambda _cfg: pytest.fail('Unknown repositories must fail before model construction'),
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'unknown_repository'


def test_answer_routing_diagnostic_needs_no_artifacts_or_generation(
    configured, monkeypatch, capsys
):
    for path in (configured.parent / 'indexes').iterdir():
        path.unlink()
    monkeypatch.setattr(
        generation_factory,
        'build_generation_provider',
        lambda _cfg: pytest.fail('Routing diagnosis must not construct a provider'),
    )
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'coderag',
            'answer',
            'En demo, handoff',
            '--config',
            str(configured),
            '--repo',
            'demo',
            '--resolve-only',
        ],
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result['mode'] == 'answer'
    assert result['routing_only']
    assert result['routing']['query'] == 'handoff'
    assert result['repository'] == 'demo'
    assert result['answer'] is None
