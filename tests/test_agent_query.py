import json
import subprocess
import sys

import pytest

from coderag import agent_query
from coderag.generation import Claim, GenerationResult


@pytest.fixture
def inputs(tmp_path):
    index = tmp_path / 'index.json'
    links = tmp_path / 'links.json'
    config = tmp_path / 'config.json'
    index.write_text(
        json.dumps(
            {
                'chunks': [
                    {
                        'id': 'a',
                        'path': 'a.py',
                        'symbol': 'save_order',
                        'start_line': 1,
                        'end_line': 2,
                        'content': 'def save_order():\n    order_id = 1',
                    }
                ]
            }
        )
    )
    links.write_text(json.dumps({'evidence_graph': {'nodes': [], 'edges': []}}))
    config.write_text(json.dumps({'generation': {'provider': 'ollama', 'model': 'test'}}))
    return ['order_id', '--index', str(index), '--relationships', str(links)], config


def invoke(argv):
    return subprocess.run(
        [sys.executable, '-m', 'coderag', 'query', *argv], capture_output=True, text=True
    )


def test_evidence_does_not_call_configured_model_and_saves_report(inputs, tmp_path):
    argv, config = inputs
    report = tmp_path / 'report.json'
    proc = invoke([*argv, '--config', str(config), '--report', str(report), '--max-chars', '12'])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data['schema_version'] == '1'
    assert data['status'] == 'ok'
    assert data['answer'] is None
    assert data['citations'][0]['chunk_id'] == 'a'
    assert data['citations'][0]['certainty'] == 'static_candidate'
    assert sum(len(item['content']) for item in data['evidence']) <= 12
    assert data['evidence'][0]['truncated']
    assert data['retrieval']['ranking_profile'] == 'identifier-v2'
    assert data['evidence'][0]['ranking']['role'] == 'reference'
    assert 'prompt' not in data
    assert json.loads(report.read_text())['generated'] is False


def test_no_matches(inputs):
    argv, _ = inputs
    proc = invoke(['xyz_nonexistent', *argv[1:]])
    assert proc.returncode == 0
    assert json.loads(proc.stdout)['status'] == 'insufficient_evidence'


@pytest.mark.parametrize('extra', [['--limit', '0'], ['--mode', 'answer'], ['--max-chars', 'bad']])
def test_errors_are_json(inputs, extra):
    argv, _ = inputs
    proc = invoke([*argv, *extra])
    assert proc.returncode == 2
    data = json.loads(proc.stdout)
    assert data['status'] == 'error'
    assert data['error']['message']


def test_missing_argument_is_json():
    proc = invoke([])
    assert proc.returncode == 2
    assert json.loads(proc.stdout)['error']['type'] == 'ArgumentError'


def test_generation_preserves_claim_links_and_redirects_progress(inputs, monkeypatch, capsys):
    argv, config = inputs

    class Provider:
        provider = 'ollama'

        def generate(self, _prompt, *, metadata=None):  # noqa: ARG002 - Provider protocol keyword
            print('model progress')  # noqa: T201 - CLI output
            return GenerationResult(
                'Found order_id',
                'ollama',
                'test',
                claims=[Claim('Static writer', 'static_candidate', ['a'])],
                citations=[{'chunk_id': 'a'}],
            )

    monkeypatch.setattr(agent_query, 'build_generation_provider', lambda _config: Provider())
    agent_query.main([*argv, '--mode', 'answer', '--config', str(config)])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert 'model progress' in captured.err
    assert data['answer'] == 'Found order_id'
    assert data['claims'][0]['citations'] == ['a']
    assert data['citations'][0]['path'] == 'a.py'


def test_invalid_generated_citations_are_errors(inputs, monkeypatch, capsys):
    argv, config = inputs

    class Provider:
        provider = 'ollama'

        def generate(self, _prompt, *, metadata=None):  # noqa: ARG002 - Provider protocol keyword
            return GenerationResult('Bad', 'ollama', 'test', citations=[{'chunk_id': 'unknown'}])

    monkeypatch.setattr(agent_query, 'build_generation_provider', lambda _config: Provider())
    with pytest.raises(SystemExit) as exc:
        agent_query.main([*argv, '--mode', 'answer', '--config', str(config)])
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'error'


def test_query_exposes_effective_limits_and_report_metadata(inputs, tmp_path):
    argv, config = inputs
    config.write_text(
        json.dumps(
            {
                'retrieval': {'limit': 2},
                'context': {'max_chars': 8, 'max_chunks': 1, 'max_tokens': 10, 'max_relations': 2},
            }
        )
    )
    report = tmp_path / 'limits-report.json'
    proc = invoke(
        [
            *argv,
            '--config',
            str(config),
            '--limit',
            '100',
            '--max-chars',
            '20',
            '--report',
            str(report),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    budget = data['retrieval'].copy()
    assert budget.pop('mode') == 'configured'
    assert budget.pop('query_plan')['lexical_transformed'] is False
    assert budget == {
        'requested_limit': 100,
        'budget_profile': None,
        'configured_limit': 2,
        'effective_limit': 2,
        'returned_results': 1,
        'limit_reached': False,
        'total_matches': None,
        'exhaustive': False,
        'ranking_profile': 'identifier-v2',
    }
    assert data['context']['effective_limits']['max_chars'] == 8
    assert data['context']['effective_limits']['max_chunks'] == 1
    assert data['context']['effective_limits']['related_limit'] == 2
    assert data['context']['content_chars'] == 8
    assert data['context']['selection']['truncated_chunks'] == 1
    assert data['evidence'][0]['returned_chars'] == 8
    assert data['evidence'][0]['original_chars'] > 8
    metadata = json.loads(report.read_text())['metadata']
    assert metadata['context'] == data['context']
    assert metadata['retrieval'] == data['retrieval']


def test_empty_query_results_still_expose_limits(inputs):
    argv, _ = inputs
    proc = invoke(['nonexistent-xyz', *argv[1:], '--limit', '1'])
    data = json.loads(proc.stdout)
    assert data['retrieval']['returned_results'] == 0
    assert data['retrieval']['total_matches'] is None
    assert data['context']['selection']['candidate_chunks'] == 0
    assert data['context']['selection']['excluded_chunks'] == 0
    assert data['context']['selection']['truncated_chunks'] == 0


def test_reaching_retrieval_limit_does_not_claim_more_matches(inputs):
    argv, _ = inputs
    proc = invoke([*argv, '--limit', '1'])
    data = json.loads(proc.stdout)
    assert data['retrieval']['limit_reached'] is True
    assert data['retrieval']['total_matches'] is None
    assert data['retrieval']['exhaustive'] is False


@pytest.fixture
def budget_inputs(inputs):
    argv, config = inputs
    index = argv[argv.index('--index') + 1]
    from pathlib import Path

    Path(index).write_text(
        json.dumps(
            {
                'chunks': [
                    {
                        'id': str(i),
                        'path': f'file{i}.py',
                        'start_line': 1,
                        'end_line': 1,
                        'content': f'order_id = {i}',
                    }
                    for i in range(12)
                ]
            }
        )
    )
    config.write_text(
        json.dumps(
            {
                'retrieval': {'limit': 10, 'mode': 'lexical'},
                'context': {'max_chunks': 3, 'max_tokens': 2500},
                'query_profiles': {
                    'code-inventory': {
                        'limit': 30,
                        'max_chunks': 10,
                        'max_chars': 40000,
                        'max_tokens': 10000,
                    }
                },
            }
        )
    )
    return [*argv, '--config', str(config)], config


def test_inventory_profile_expands_context_without_changing_normal_queries(budget_inputs):
    argv, config = budget_inputs
    before = config.read_bytes()
    normal = json.loads(invoke(argv).stdout)
    expanded = json.loads(invoke([*argv, '--budget-profile', 'code-inventory']).stdout)
    assert len(normal['evidence']) == 3
    assert normal['retrieval']['effective_limit'] == 10
    assert normal['context']['effective_limits']['max_tokens'] == 2500
    assert len(expanded['evidence']) == 10
    assert expanded['retrieval']['effective_limit'] == 30
    assert expanded['retrieval']['returned_results'] == 12
    assert expanded['retrieval']['budget_profile'] == 'code-inventory'
    assert expanded['context']['effective_limits']['max_chars'] == 40000
    assert expanded['context']['effective_limits']['max_tokens'] == 10000
    assert config.read_bytes() == before


def test_profile_cli_can_reduce_budgets_but_not_exceed_profile_caps(budget_inputs):
    argv, _ = budget_inputs
    result = invoke(
        [
            *argv,
            '--budget-profile',
            'code-inventory',
            '--limit',
            '200',
            '--max-chunks',
            '2',
            '--max-chars',
            '20',
        ]
    )
    data = json.loads(result.stdout)
    assert result.returncode == 0
    assert data['retrieval']['effective_limit'] == 30
    assert len(data['evidence']) <= 2
    assert sum(len(e['content']) for e in data['evidence']) <= 20


def test_profile_pagination_keeps_expanded_budget_on_continuation(budget_inputs):
    argv, _ = budget_inputs
    args = [*argv, '--budget-profile', 'code-inventory']
    first = json.loads(invoke([*args, '--page-size', '6']).stdout)
    second = json.loads(invoke([*args, '--cursor', first['pagination']['next_cursor']]).stdout)
    assert len(first['evidence']) == len(second['evidence']) == 6
    assert second['pagination']['session']['reused']
    assert second['context']['effective_limits']['max_tokens'] == 10000
    assert second['retrieval']['effective_limit'] == 30
    assert {e['chunk_id'] for e in first['evidence']}.isdisjoint(
        {e['chunk_id'] for e in second['evidence']}
    )
    changed = invoke([*argv, '--cursor', first['pagination']['next_cursor']])
    assert changed.returncode == 2
    assert json.loads(changed.stdout)['error']['code'] == 'stale_cursor'


@pytest.mark.parametrize(
    'profile',
    [
        {'limit': True},
        {'max_tokens': 0},
        {'max_chars': -1},
        {'max_chunks': '10'},
        {'provider': 'remote'},
        [],
    ],
)
def test_invalid_budget_profiles_are_rejected(budget_inputs, profile):
    argv, config = budget_inputs
    raw = json.loads(config.read_text())
    raw['query_profiles']['code-inventory'] = profile
    config.write_text(json.dumps(raw))
    assert invoke([*argv, '--budget-profile', 'code-inventory']).returncode == 2


def test_budget_profile_cannot_be_used_for_generation(budget_inputs):
    argv, _ = budget_inputs
    proc = invoke([*argv, '--budget-profile', 'code-inventory', '--mode', 'answer'])
    assert proc.returncode == 2
    assert 'evidence mode' in json.loads(proc.stdout)['error']['message']


def test_profile_accepts_unset_optional_central_sections(budget_inputs):
    argv, config = budget_inputs
    raw = json.loads(config.read_text())
    raw.update(context=None, retrieval=None)
    config.write_text(json.dumps(raw))
    proc = invoke([*argv, '--budget-profile', 'code-inventory'])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert len(data['evidence']) == 10
    assert data['retrieval']['effective_limit'] == 30
