"""Local Git provenance and source freshness are independent; diagnostics never rebuild."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from coderag import agent_query, git_state
from coderag.core import index_repository
from coderag.doctor import diagnose
from coderag.evidence_graph import build_evidence_graph
from coderag.preparation import ReadinessError, assess_sources, source_spec
from coderag.repo_links import build_repository_links, save_links


def git(repo, *args):
    return subprocess.run(
        [
            'git',
            '-c',
            'user.name=Code RAG Test',
            '-c',
            'user.email=test@example.invalid',
            '-c',
            'commit.gpgsign=false',
            '-c',
            'core.hooksPath=/dev/null',
            '-C',
            str(repo),
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
        env={key: value for key, value in os.environ.items() if not key.startswith('GIT_')},
    ).stdout.strip()


@pytest.fixture
def prepared(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    (repo / 'api.py').write_text(
        'def order_id():\n    return 1\n\ndef read_order_id():\n    return 2\n'
    )
    (repo / 'README.md').write_text('initial docs')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'initial')
    config = tmp_path / 'config.json'
    raw = {
        'repositories': {'demo': {'path': 'repo'}},
        'retrieval': {'mode': 'lexical'},
        'generation': {'provider': 'must-not-call'},
        'indexing': {
            'languages': ['python'],
            'chunking': {
                'strategy': 'structural',
                'max_tokens': 100,
                'overlap_tokens': 0,
                'preserve_symbols': True,
                'include_parent_context': True,
                'on_missing_parser': 'error',
            },
        },
    }
    config.write_text(json.dumps(raw))
    index = tmp_path / 'indexes/demo.chunks.json'
    links = tmp_path / 'indexes/demo.relationships.json'

    def rebuild():
        data = index_repository(repo, index, raw, incremental=True)
        report = build_repository_links(raw, config, 'demo')
        report['evidence_graph'] = build_evidence_graph({'demo': data}, report)
        save_links(links, report)
        return data

    data = rebuild()

    def query(*flags):
        parser = agent_query.QueryParser()
        agent_query.configure_parser(parser)
        return agent_query.run(
            parser.parse_args(
                [
                    'order_id',
                    '--config',
                    str(config),
                    '--repo',
                    'demo',
                    *flags,
                ]
            )
        )

    return repo, config, raw, index, links, data, rebuild, query


def test_index_records_clean_commit_and_read_only_diagnostics(prepared):
    repo, config, _, index, links, data, _, query = prepared
    recorded = data['git']
    assert recorded['commit'] == git(repo, 'rev-parse', 'HEAD')
    assert recorded['branch'] == 'main'
    assert recorded['dirty'] is False
    assert recorded['reference_stable']
    before = index.read_bytes(), links.read_bytes(), (repo / '.git/index').read_bytes()
    result = query()['readiness']
    assert result['git']['status'] == 'current'
    assert result['needs_update'] is False
    checks = diagnose(config, full=True)['checks']
    check = next(c for c in checks if c['code'] == 'git')
    assert check['status'] == 'ok'
    assert check['git']['indexed']['commit'] == recorded['commit']
    assert before == (index.read_bytes(), links.read_bytes(), (repo / '.git/index').read_bytes())


@pytest.mark.parametrize('indexed_file', [False, True])
def test_commits_trigger_hash_verification_and_only_source_changes_need_update(
    prepared, indexed_file
):
    repo, _, _, index, _, data, rebuild, query = prepared
    path = repo / ('api.py' if indexed_file else 'README.md')
    path.write_text(path.read_text() + '\n# new content\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'next')
    before = index.read_bytes()
    report = query()['readiness']
    assert report['git']['indexed']['commit'] == data['git']['commit']
    assert report['git']['current']['commit'] == git(repo, 'rev-parse', 'HEAD')
    assert report['git']['relation'] == 'ahead'
    assert report['git']['ahead'] == 1
    assert report['source']['verification'] == 'sha256'
    assert report['needs_update'] is indexed_file
    assert index.read_bytes() == before
    if indexed_file:
        with pytest.raises(ReadinessError) as exc:
            query('--require-fresh')
        assert exc.value.code == 'source_not_fresh'
    else:
        assert query('--require-fresh')['readiness']['needs_update'] is False
    updated = rebuild()
    assert updated['git']['commit'] != data['git']['commit']
    if not indexed_file:
        assert updated['chunks'] == data['chunks']
    assert query()['readiness']['git']['status'] == 'current'


def test_local_source_edits_and_dirty_snapshot_are_not_a_clean_commit(prepared):
    repo, _, _, _, _, data, rebuild, query = prepared
    (repo / 'api.py').write_text('def order_id(): return 9\n')
    state = query()['readiness']
    assert state['git']['relation'] == 'same_commit'
    assert state['git']['current']['dirty']
    assert state['needs_update'] is True
    dirty = rebuild()
    assert dirty['git']['commit'] == data['git']['commit']
    assert dirty['git']['dirty']
    assert query()['readiness']['needs_update'] is False


def test_detached_head_and_diverged_history(prepared):
    repo, _, _, _, _, initial, rebuild, query = prepared
    (repo / 'README.md').write_text('branch A docs')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'branch A')
    branch_a = rebuild()
    git(repo, 'checkout', '--detach', initial['git']['commit'])
    report = query()['readiness']
    assert report['git']['current']['branch'] is None
    assert report['git']['relation'] == 'behind'
    assert report['needs_update'] is False
    (repo / 'README.md').write_text('branch B docs')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'branch B')
    report = query()['readiness']
    assert report['git']['indexed']['commit'] == branch_a['git']['commit']
    assert report['git']['relation'] == 'diverged'
    assert report['needs_update'] is False


def test_subdirectory_and_linked_worktree(prepared, tmp_path):
    repo, _, raw, _, _, data, _, _ = prepared
    nested = repo / 'nested'
    nested.mkdir()
    assert git_state.capture_git(nested)['commit'] == data['git']['commit']
    linked = tmp_path / 'linked'
    git(repo, 'worktree', 'add', '-b', 'other', str(linked))
    assert (linked / '.git').is_file()
    indexed = index_repository(linked, tmp_path / 'linked-index.json', raw)
    assert indexed['git']['commit'] == data['git']['commit']
    assert indexed['git']['branch'] == 'other'


def test_legacy_and_unavailable_git_do_not_claim_commit_freshness(prepared, monkeypatch):
    repo, _, raw, index, _, data, _, _ = prepared
    legacy = {k: v for k, v in data.items() if k != 'git'}
    result = assess_sources(source_spec(legacy, raw, 'demo', index))
    assert result['git']['status'] == 'unknown'

    def missing(*_args):
        raise FileNotFoundError('git missing')

    monkeypatch.setattr(git_state, 'git', missing)
    assert git_state.capture_git(repo)['status'] == 'unavailable'
    assert assess_sources(source_spec(data, raw, 'demo', index))['status'] == 'current'


def test_non_git_and_unborn_worktree(prepared, tmp_path):
    _, _, _, _, _, _, _, _ = prepared
    plain = tmp_path / 'plain'
    plain.mkdir()
    assert git_state.capture_git(plain)['status'] == 'not_repository'
    git(plain, 'init', '-b', 'empty')
    state = git_state.capture_git(plain)
    assert state['status'] == 'available'
    assert state['commit'] is None
    assert state['branch'] == 'empty'


def test_ref_change_during_indexing_is_recorded_as_unstable(prepared, monkeypatch):
    repo, _, raw, index, _, _, _, _ = prepared
    first = git_state.capture_git(repo)
    last = {**first, 'commit': 'a' * 40}
    calls = iter([first, last])
    monkeypatch.setattr(git_state, 'capture_git', lambda _root: next(calls))
    result = index_repository(repo, index, raw)
    assert result['git']['start_commit'] == first['commit']
    assert result['git']['commit'] == last['commit']
    assert result['git']['reference_stable'] is False


def test_repository_fsmonitor_is_not_executed(prepared, tmp_path):
    repo, _, _, _, _, _, _, _ = prepared
    marker = tmp_path / 'hook-was-run'
    hook = tmp_path / 'fsmonitor'
    hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    hook.chmod(0o700)
    git(repo, 'config', 'core.fsmonitor', str(hook))
    assert git_state.capture_git(repo)['status'] == 'available'
    assert not marker.exists()


def test_paged_sessions_keep_git_assessment_without_loading_artifacts(prepared, monkeypatch):
    repo, config, _, index, links, data, _, query = prepared
    first = query('--page-size', '1')
    cursor = first['pagination']['next_cursor']
    assert cursor
    (repo / 'README.md').write_text('next docs')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'docs')
    import coderag.preparation as preparation

    clock = first['readiness']['source']['valid_until'] + 1
    monkeypatch.setattr(preparation.time, 'time', lambda: clock)
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path in {config, index, links}:
            pytest.fail('Cached continuation must not reread full artifacts')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guarded)
    report = query('--cursor', cursor)['readiness']
    assert report['git']['indexed']['commit'] == data['git']['commit']
    assert report['git']['relation'] == 'ahead'
    assert report['needs_update'] is False


def test_repository_clean_filter_is_not_executed(prepared, tmp_path):
    repo, _, _, _, _, _, _, _ = prepared
    (repo / '.gitattributes').write_text('api.py filter=custom\n')
    git(repo, 'add', '.gitattributes')
    git(repo, 'commit', '-m', 'attributes')
    marker = tmp_path / 'filter-was-run'
    hook = tmp_path / 'clean-filter'
    hook.write_text(f'#!/bin/sh\ntouch "{marker}"\ncat\n')
    hook.chmod(0o700)
    git(repo, 'config', 'filter.custom.clean', str(hook))
    (repo / 'api.py').write_text('def order_id(): return 99\n')
    assert git_state.capture_git(repo)['status'] == 'available'
    assert not marker.exists()


def test_git_environment_cannot_redirect_provenance(prepared, monkeypatch):
    repo, _, _, _, _, data, _, _ = prepared
    monkeypatch.setenv('GIT_DIR', '/nonexistent-git-directory')
    assert git_state.capture_git(repo)['commit'] == data['git']['commit']


def test_answer_exposes_commit_state_without_rewriting_provider_text(
    prepared, monkeypatch, capsys, tmp_path
):
    import sys

    from coderag import __main__ as cli, generation_factory
    from coderag.answer_display import render_answer
    from coderag.generation import GenerationResult

    repo, config, raw, index, _, data, _, _ = prepared
    raw['generation'] = {'provider': 'ollama', 'model': 'test'}
    config.write_text(json.dumps(raw))
    (repo / 'README.md').write_text('new documentation')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'docs')
    before = index.read_bytes()
    text = 'Respuesta literal del proveedor.\n'
    generated = GenerationResult(
        text, 'ollama', 'test', citations=[{'chunk_id': data['chunks'][0]['id']}]
    )

    class Provider:
        provider = 'ollama'

        def generate(self, prompt, *, metadata=None):  # noqa: ARG002 - provider protocol
            assert 'order_id' in prompt
            return generated

    monkeypatch.setattr(generation_factory, 'build_generation_provider', lambda _config: Provider())
    report = tmp_path / 'answer-report.json'
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'coderag',
            'answer',
            'order_id',
            '--config',
            str(config),
            '--repo',
            'demo',
            '--report',
            str(report),
        ],
    )
    cli.main()
    output = json.loads(capsys.readouterr().out)
    state = output['index_state']
    assert state['git']['relation'] == 'ahead'
    assert state['needs_update'] is False
    assert json.loads(report.read_text())['metadata']['index_state'] == state
    assert index.read_bytes() == before
    payload = {'answer': generated, 'index_state': state, 'context': {'items': []}}
    assert render_answer(payload) == text
    display = render_answer(payload, include_evidence=True, markdown=True)
    assert text in display
    assert data['git']['commit'] in display
    assert state['git']['current']['commit'] in display
    assert 'Actualización necesaria: no' in display
