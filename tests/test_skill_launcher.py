"""Exercise central configuration lookup from outside the CodeTrace checkout."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'skills/code-trace/scripts/query.py'


def test_inventory_skill_retrieves_without_generation(tmp_path, checkout):
    root, config = checkout
    pipeline = json.loads((root / 'config.json').read_text())
    pipeline['generation'] = {'provider': 'invalid-provider-must-not-be-used'}
    (root / 'config.json').write_text(json.dumps(pipeline))
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / 'skills/code-trace-inventory/scripts/query.py'),
            'En other, order_id',
            '--config',
            str(config),
            '--report',
            'inventory-evidence.json',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result['mode'] == 'evidence'
    assert result['repository'] == 'other'
    assert result['answer'] is None
    assert result['citations'][0]['path'] == 'other.py'
    assert len(result['evidence'][0]['content']) == 5
    assert (tmp_path / 'inventory-evidence.json').is_file()


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / 'code rag'
    root.mkdir()
    (root / 'src').symlink_to(ROOT / 'src', target_is_directory=True)
    (root / '.venv').symlink_to(ROOT / '.venv', target_is_directory=True)
    (root / 'indexes').mkdir()
    for name in ('demo', 'other'):
        (root / 'indexes' / f'{name}.chunks.json').write_text(
            json.dumps(
                {
                    'chunks': [
                        {
                            'id': name,
                            'path': f'{name}.py',
                            'content': 'order_id = 1',
                            'start_line': 1,
                            'end_line': 1,
                        }
                    ]
                }
            )
        )
        (root / 'indexes' / f'{name}.relationships.json').write_text(
            json.dumps({'evidence_graph': {'nodes': [], 'edges': []}})
        )
    (root / 'config.json').write_text(
        json.dumps(
            {
                'default_repository': 'demo',
                'repositories': {name: {} for name in ('demo', 'other')},
                'context': {'max_chars': 5},
                'generation': {'provider': 'ollama', 'model': 'unused-in-evidence-mode'},
            }
        )
    )
    settings_dir = tmp_path / 'settings with spaces'
    settings_dir.mkdir()
    config = settings_dir / 'local.json'
    config.write_text(json.dumps({'code_trace_root': '../code rag', 'repo': 'demo'}))
    return root, config


def invoke_inventory(tmp_path, config, *extra):
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / 'skills/code-trace-inventory/scripts/query.py'),
            'order_id',
            '--config',
            str(config),
            *extra,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize('repo', ['demo', 'other'])
def test_launcher_uses_central_repository_and_pipeline_config(tmp_path, checkout, repo):
    _root, config = checkout
    settings = json.loads(config.read_text())
    settings['repo'] = repo
    config.write_text(json.dumps(settings))
    proc = invoke_inventory(tmp_path, config, '--report', 'relative-report.json')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result['status'] == 'ok'
    assert result['citations'][0]['path'] == f'{repo or "demo"}.py'
    assert len(result['evidence'][0]['content']) == 5
    assert result['answer'] is None
    report = json.loads((tmp_path / 'relative-report.json').read_text())
    assert report['query'] == 'order_id'
    assert report['context']['max_chars'] == 5


def test_launcher_reports_unknown_repository(tmp_path, checkout):
    _, config = checkout
    settings = json.loads(config.read_text())
    settings['repo'] = 'missing'
    config.write_text(json.dumps(settings))
    proc = invoke_inventory(tmp_path, config)
    assert proc.returncode == 2
    assert 'Repository not configured' in json.loads(proc.stdout)['error']['message']


def test_launcher_reports_missing_relationships(tmp_path, checkout):
    root, config = checkout
    (root / 'indexes/demo.relationships.json').unlink()
    proc = invoke_inventory(tmp_path, config)
    assert proc.returncode == 2
    assert 'run CodeTrace index and link' in json.loads(proc.stdout)['error']['message']


def test_launcher_missing_config_returns_json_without_traceback(tmp_path):
    proc = invoke_inventory(tmp_path, tmp_path / 'missing.json')
    assert proc.returncode == 2
    assert json.loads(proc.stdout)['error']['type'] == 'FileNotFoundError'
    assert 'Traceback' not in proc.stderr


def test_launcher_supports_repository_override(tmp_path, checkout):
    _, config = checkout
    proc = invoke_inventory(tmp_path, config, '--repo', 'other')
    assert proc.returncode == 0
    assert json.loads(proc.stdout)['repository'] == 'other'


def test_missing_skill_repo_does_not_use_central_default(tmp_path, checkout):
    _, config = checkout
    settings = json.loads(config.read_text())
    settings.pop('repo')
    config.write_text(json.dumps(settings))
    proc = invoke_inventory(tmp_path, config)
    assert proc.returncode == 2
    assert 'set repo in the skill configuration' in json.loads(proc.stdout)['error']['message']


@pytest.mark.parametrize('repo', ['missing', '', None, ['other'], 42])
def test_invalid_skill_repository_does_not_fall_back(tmp_path, checkout, repo):
    _, config = checkout
    settings = json.loads(config.read_text())
    settings['repo'] = repo
    config.write_text(json.dumps(settings))
    proc = invoke_inventory(tmp_path, config)
    assert proc.returncode == 2
    assert 'Repository not configured' in json.loads(proc.stdout)['error']['message']


def test_natural_language_routes_to_another_repository_and_saves_selection(tmp_path, checkout):
    root, config = checkout
    pipeline_path = root / 'config.json'
    pipeline = json.loads(pipeline_path.read_text())
    pipeline['repositories']['other']['aliases'] = ['pruebas remotas']
    pipeline_path.write_text(json.dumps(pipeline))
    report = tmp_path / 'routing-report.json'
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / 'skills/code-trace-inventory/scripts/query.py'),
            'En pruebas remotas, order_id',
            '--config',
            str(config),
            '--report',
            str(report),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result['repository'] == 'other'
    assert result['routing']['reason'] == 'alias'
    assert result['citations'][0]['path'] == 'other.py'
    assert json.loads(report.read_text())['metadata']['routing']['repository'] == 'other'


def test_routing_only_does_not_require_indexes(tmp_path, checkout):
    root, config = checkout
    (root / 'indexes/other.chunks.json').unlink()
    proc = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            'En other, order_id',
            '--config',
            str(config),
            '--resolve-only',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result['routing_only']
    assert result['repository'] == 'other'
    assert result['evidence'] == []


def test_ambiguous_routing_returns_candidates_without_querying(tmp_path, checkout):
    root, config = checkout
    (root / 'indexes/demo.chunks.json').unlink()
    proc = subprocess.run(
        [sys.executable, str(LAUNCHER), 'En demo y other, order_id', '--config', str(config)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    error = json.loads(proc.stdout)['error']
    assert error['code'] == 'ambiguous_repository'
    assert error['candidates'] == ['demo', 'other']


def test_default_skill_invokes_answer_with_deterministic_evidence_output(
    checkout, monkeypatch, capsys
):
    import importlib.util

    spec = importlib.util.spec_from_file_location('skill_query', LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    root, config = checkout
    commands = []
    rendered = 'Respuesta del proveedor.\n\n## Evidencias del contexto\nFuente literal.'

    def run(command, *, cwd):
        commands.append(command)
        assert cwd == root
        sys.stdout.write(rendered)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.subprocess, 'run', run)
    assert launcher.main(['order_id', '--config', str(config)]) == 0
    assert commands[0][1:3] == ['-m', 'codetrace']
    assert commands[0][3] == 'answer'
    assert commands[0][commands[0].index('--output-format') + 1] == 'markdown'
    assert '--include-evidence' in commands[0]
    assert capsys.readouterr().out == rendered


def test_inventory_skill_continues_evidence_pages(tmp_path, checkout):
    root, config = checkout
    index_path = root / 'indexes/demo.chunks.json'
    index = json.loads(index_path.read_text())
    second = {**index['chunks'][0], 'id': 'second', 'path': 'second.py'}
    index['chunks'].append(second)
    index_path.write_text(json.dumps(index))
    base = [
        sys.executable,
        str(ROOT / 'skills/code-trace-inventory/scripts/query.py'),
        'order_id',
        '--config',
        str(config),
    ]
    first = subprocess.run(
        [*base, '--page-size', '1'], cwd=tmp_path, capture_output=True, text=True
    )
    assert first.returncode == 0, first.stderr
    page = json.loads(first.stdout)
    cursor = page['pagination']['next_cursor']
    assert cursor
    second = subprocess.run(
        [*base, '--cursor', cursor], cwd=tmp_path, capture_output=True, text=True
    )
    assert second.returncode == 0, second.stderr
    next_page = json.loads(second.stdout)
    assert next_page['pagination']['has_more'] is False
    assert page['matches'][0]['chunk_id'] != next_page['matches'][0]['chunk_id']
    assert next_page['answer'] is None


def test_inventory_skill_forwards_source_scope(tmp_path, checkout):
    root, config = checkout
    index_path = root / 'indexes/demo.chunks.json'
    data = json.loads(index_path.read_text())
    data['chunks'][0]['language'] = 'python'
    data['chunks'].append(
        {'id': 'noise', 'path': 'noise.json', 'language': 'json', 'content': 'order_id'}
    )
    index_path.write_text(json.dumps(data))
    report = tmp_path / 'scope-report.json'
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / 'skills/code-trace-inventory/scripts/query.py'),
            'order_id',
            '--config',
            str(config),
            '--file',
            'demo.py',
            '--source-type',
            'python',
            '--retrieval-mode',
            'lexical',
            '--report',
            str(report),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert [cite['path'] for cite in result['citations']] == ['demo.py']
    assert result['retrieval']['source_scope']['eligible_chunks'] == 1
    assert result['retrieval']['mode'] == 'lexical'
    assert (
        json.loads(report.read_text())['metadata']['retrieval']['source_scope']
        == (result['retrieval']['source_scope'])
    )


def test_inventory_launcher_selects_central_budget_profile(tmp_path, checkout):
    root, config = checkout
    pipeline_path = root / 'config.json'
    pipeline = json.loads(pipeline_path.read_text())
    pipeline['query_profiles'] = {
        'code-trace-inventory': {
            'limit': 30,
            'max_chunks': 10,
            'max_chars': 40000,
            'max_tokens': 10000,
        }
    }
    pipeline_path.write_text(json.dumps(pipeline))
    command = [
        sys.executable,
        str(ROOT / 'skills/code-trace-inventory/scripts/query.py'),
        'order_id',
        '--config',
        str(config),
    ]
    proc = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data['retrieval']['effective_limit'] == 30
    assert data['context']['effective_limits']['max_chunks'] == 10
    assert data['context']['effective_limits']['max_chars'] == 40000
    assert data['evidence'][0]['content'] == 'order_id = 1'
    reduced = subprocess.run([*command, '--max-chars', '4'], capture_output=True, text=True)
    assert len(json.loads(reduced.stdout)['evidence'][0]['content']) == 4


@pytest.mark.parametrize('skill', ['code-trace', 'code-trace-inventory'])
def test_skill_explicit_repo_is_routing_metadata_not_search_text(checkout, skill):
    _, config = checkout
    command = [
        sys.executable,
        str(ROOT / 'skills' / skill / 'scripts/query.py'),
        'Where is order_id used?',
        '--config',
        str(config),
        '--repo',
        'other',
        '--resolve-only',
    ]
    proc = subprocess.run(command, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result['repository'] == 'other'
    assert result['routing']['query'] == 'Where is order_id used?'


@pytest.mark.parametrize(
    'question',
    [
        'cuantas tools intervienen en el handoff --repo fabrica',
        '¿Dónde se define handoff?',
        '¿Cuántas tools hay declaradas?',
    ],
)
def test_code_rag_always_answers_even_count_or_behavior_questions(checkout, monkeypatch, question):
    import importlib.util

    spec = importlib.util.spec_from_file_location('answer_only_skill', LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    root, config = checkout
    commands = []

    def run(command, *, cwd):
        assert cwd == root
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.subprocess, 'run', run)
    assert launcher.main([question, '--config', str(config)]) == 0
    assert len(commands) == 1
    assert commands[0][3:5] == ['answer', question]
    assert '--include-evidence' in commands[0]
    assert '--mode' not in commands[0]
    assert not {'--limit', '--max-chunks', '--max-chars'} & set(commands[0])


@pytest.mark.parametrize('mode', ['inventory', 'evidence'])
def test_code_rag_rejects_other_modes_before_invoking_any_backend(checkout, monkeypatch, mode):
    import importlib.util

    spec = importlib.util.spec_from_file_location('answer_only_skill', LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    _, config = checkout
    monkeypatch.setattr(
        launcher.subprocess, 'run', lambda *_a, **_kw: pytest.fail('No alternate backend may run')
    )
    with pytest.raises(SystemExit) as exc:
        launcher.main(
            ['cuantas tools intervienen en handoff', '--config', str(config), '--mode', mode]
        )
    assert exc.value.code == 2


def test_code_rag_provider_errors_do_not_fall_back_to_inventory_or_query(checkout, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location('answer_only_skill', LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    _, config = checkout
    calls = []

    def fail(command, *, cwd):  # noqa: ARG001 - subprocess protocol
        calls.append(command)
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(launcher.subprocess, 'run', fail)
    assert launcher.main(['cuantas tools intervienen en handoff', '--config', str(config)]) == 2
    assert len(calls) == 1
    assert calls[0][3] == 'answer'


def test_code_rag_forwards_explicit_budgets_only(checkout, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location('answer_only_skill', LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    _, config = checkout
    calls = []

    def run(command, *, cwd):  # noqa: ARG001 - subprocess protocol
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.subprocess, 'run', run)
    assert (
        launcher.main(
            [
                'handoff',
                '--config',
                str(config),
                '--limit',
                '7',
                '--max-chunks',
                '2',
                '--mode',
                'answer',
            ]
        )
        == 0
    )
    assert calls[0][calls[0].index('--limit') + 1] == '7'
    assert calls[0][calls[0].index('--max-chunks') + 1] == '2'
    assert '--max-chars' not in calls[0]


def test_code_rag_uses_central_model_and_budgets_for_the_original_count_question(
    checkout, monkeypatch, capsys, tmp_path
):
    import importlib.util

    from coderag import __main__ as cli, generation_factory
    from coderag.generation import GenerationResult

    root, config = checkout
    pipeline_path = root / 'config.json'
    pipeline = json.loads(pipeline_path.read_text())
    pipeline['repositories']['fabrica'] = {}
    pipeline['retrieval'] = {'limit': 22, 'mode': 'lexical'}
    pipeline['context'] = {'max_chunks': 7, 'max_chars': 20000, 'max_tokens': 6000}
    pipeline['generation'] = {'provider': 'ollama', 'model': 'configured-model'}
    pipeline_path.write_text(json.dumps(pipeline))
    content = 'def human_handoff():\n    return "handoff"\n' + '# tool detail\n' * 1000 + '# END'
    (root / 'indexes/fabrica.chunks.json').write_text(
        json.dumps(
            {
                'chunks': [
                    {
                        'id': 'handoff',
                        'path': 'tools/handoff.py',
                        'content': content,
                        'start_line': 1,
                        'end_line': 1003,
                    }
                ]
            }
        )
    )
    (root / 'indexes/fabrica.relationships.json').write_text('{"evidence_graph": {}}')

    class Provider:
        provider = 'ollama'

        def generate(self, prompt, *, metadata=None):  # noqa: ARG002 - provider protocol
            assert 'cuantas tools intervienen en el handoff' in prompt
            assert '--repo fabrica' not in prompt
            assert content in prompt
            return GenerationResult(
                'Una herramienta en la evidencia; total no exhaustivo.',
                'ollama',
                'configured-model',
                citations=[{'chunk_id': 'handoff'}],
            )

    def build_provider(settings):
        assert settings.provider == 'ollama'
        assert settings.model == 'configured-model'
        return Provider()

    monkeypatch.setattr(generation_factory, 'build_generation_provider', build_provider)
    spec = importlib.util.spec_from_file_location('answer_only_skill', LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    calls = []

    def run(command, *, cwd):
        assert cwd == root
        assert command[3] == 'answer'
        calls.append(command)
        with monkeypatch.context() as inner:
            inner.setattr(sys, 'argv', command[2:])
            cli.main()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.subprocess, 'run', run)
    report = tmp_path / 'answer-report.json'
    assert (
        launcher.main(
            [
                'cuantas tools intervienen en el handoff --repo fabrica',
                '--config',
                str(config),
                '--report',
                str(report),
            ]
        )
        == 0
    )
    saved = json.loads(report.read_text())
    assert len(calls) == 1
    assert saved['retrieval_config']['limit'] == 22
    assert saved['context']['max_chars'] == 20000
    assert len(saved['context']['items'][0]['content']) > 12000
    assert 'Una herramienta en la evidencia; total no exhaustivo.' in capsys.readouterr().out


def test_code_rag_with_disabled_provider_reports_error_without_alternative_mode(tmp_path, checkout):
    root, config = checkout
    pipeline_path = root / 'config.json'
    pipeline = json.loads(pipeline_path.read_text())
    pipeline['generation'] = {'provider': 'none'}
    pipeline_path.write_text(json.dumps(pipeline))
    proc = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            'cuantas tools intervienen en el handoff',
            '--config',
            str(config),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    data = json.loads(proc.stdout)
    assert not data['generated']
    assert 'configured generation provider' in data['error']['message']
    assert 'Inventario' not in proc.stdout


@pytest.mark.parametrize('skill', ['code-trace', 'code-trace-inventory'])
def test_legacy_connection_field_is_accepted_but_conflicts_fail(checkout, skill):
    _, config = checkout
    settings = json.loads(config.read_text())
    settings['code_rag_root'] = settings.pop('code_trace_root')
    config.write_text(json.dumps(settings))
    command = [
        sys.executable,
        str(ROOT / 'skills' / skill / 'scripts/query.py'),
        'order_id',
        '--config',
        str(config),
        '--resolve-only',
    ]
    proc = subprocess.run(command, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)['repository'] == 'demo'
    settings['code_trace_root'] = '/another/checkout'
    config.write_text(json.dumps(settings))
    proc = subprocess.run(command, capture_output=True, text=True)
    assert proc.returncode == 2
    assert 'Conflicting' in json.loads(proc.stdout)['error']['message']


def test_legacy_inventory_budget_profile_is_preserved(checkout, tmp_path):
    root, config = checkout
    pipeline = json.loads((root / 'config.json').read_text())
    pipeline['query_profiles'] = {'code-inventory': {'max_chars': 4}}
    (root / 'config.json').write_text(json.dumps(pipeline))
    result = invoke_inventory(tmp_path, config)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(json.loads(result.stdout)['evidence'][0]['content']) == 4
