import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/build_indexes.py'
spec = importlib.util.spec_from_file_location('build_indexes', SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def config(tmp_path):
    for name in ('app', 'lib'):
        source = tmp_path / name
        source.mkdir()
        (source / 'example.py').write_text('def save_order():\n    return 1\n')
    path = tmp_path / 'settings.json'
    path.write_text(
        json.dumps(
            {
                'repositories': {name: {'path': name} for name in ('app', 'lib')},
                'relationships': {'app': {'dependencies': ['lib']}},
                'indexing': {
                    'languages': ['python'],
                    'exclude': [],
                    'isolate_parsers': False,
                    'chunking': {
                        'strategy': 'structural',
                        'max_tokens': 100,
                        'overlap_tokens': 5,
                        'preserve_symbols': True,
                        'include_parent_context': True,
                        'on_missing_parser': 'error',
                    },
                },
            }
        )
    )
    return path


def test_selected_repository_includes_dependencies_and_indexes_before_links(config):
    plan = builder.build_plan(config, ['app'], incremental=True)
    assert [command[2] for command in plan] == ['index', 'index', 'link', 'link']
    assert [command[command.index('--repo') + 1] for command in plan] == [
        'app',
        'lib',
        'app',
        'lib',
    ]
    assert all('--incremental' in command for command in plan[:2])


def test_preflight_rejects_missing_source_without_writes(config):
    raw = json.loads(config.read_text())
    raw['repositories']['missing'] = {'path': 'missing'}
    config.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='source directory not found'):
        builder.build_plan(config)
    assert not (config.parent / 'indexes').exists()


def test_unknown_repository(config):
    with pytest.raises(ValueError, match='Repository not configured'):
        builder.build_plan(config, ['unknown'])


def test_build_and_incremental_update_from_other_directory(config, tmp_path):
    argv = [sys.executable, str(SCRIPT), '--config', str(config)]
    dry = subprocess.run([*argv, '--dry-run'], cwd=tmp_path, capture_output=True, text=True)
    assert dry.returncode == 0, dry.stderr
    assert not (tmp_path / 'indexes').exists()
    for extra in ([], ['--incremental']):
        proc = subprocess.run([*argv, *extra], cwd=tmp_path, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        for name in ('app', 'lib'):
            chunks = json.loads((tmp_path / f'indexes/{name}.chunks.json').read_text())
            relationships = json.loads(
                (tmp_path / f'indexes/{name}.relationships.json').read_text()
            )
            assert chunks['chunks']
            assert relationships['evidence_graph']['nodes']
            assert relationships['index_sources'][name]['output'] == f'indexes/{name}.chunks.json'


def test_semantic_preparation_runs_after_all_links_and_uses_distinct_outputs(config):
    raw = json.loads(config.read_text())
    raw['retrieval'] = {'semantic_enabled': True}
    config.write_text(json.dumps(raw))
    plan = builder.build_plan(config)
    assert [command[2] for command in plan] == ['index', 'index', 'link', 'link', 'embed', 'embed']
    raw['retrieval'].update(semantic_v1_store='shared-v1.json', semantic_v2_store='shared-v2.json')
    config.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='shared'):
        builder.build_plan(config)


@pytest.mark.parametrize(
    ('returncode', 'expected', 'message'), [(-11, 139, 'SIGSEGV (11)'), (2, 2, 'exit code 2')]
)
def test_failed_command_reports_signal_and_preserves_useful_exit_code(
    config, monkeypatch, capsys, returncode, expected, message
):
    launches = []

    def fail(command, **_kwargs):
        launches.append(command)
        raise subprocess.CalledProcessError(returncode, command)

    monkeypatch.setattr(builder.subprocess, 'run', fail)
    assert builder.main(['--config', str(config)]) == expected
    assert len(launches) == 1
    assert launches[0][1:3] == ['-X', 'faulthandler']
    assert message in capsys.readouterr().err


def test_repository_output_field_is_rejected_before_writing(config):
    raw = json.loads(config.read_text())
    raw['repositories']['app']['output'] = 'old.chunks.json'
    config.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='remove output'):
        builder.build_plan(config)
    assert not (config.parent / 'indexes').exists()


def test_make_clean_removes_both_adapters_and_allows_a_clean_rebuild(config):
    root = config.parent
    indexes = root / 'indexes'
    indexes.mkdir()
    raw = json.loads(config.read_text())
    raw['repositories']['app']['retrieval'] = {
        'semantic_enabled': False,
        'semantic_v1_store': 'custom/base.json',
        'semantic_v2_store': 'custom/enriched.json',
    }
    config.write_text(json.dumps(raw))
    custom = root / 'custom'
    custom.mkdir()
    commands = ['make', f'CONFIG={config}', f'PYTHON={sys.executable}', 'REPOS=app']
    subprocess.run([*commands, 'indexes'], cwd=ROOT, check=True, capture_output=True)

    snapshots = [
        indexes / f'{repo}.{suffix}'
        for repo in ('app', 'lib')
        for suffix in ('chunks.json', 'chunks.sqlite3', 'relationships.json')
    ]
    assert all(path.is_file() for path in snapshots)
    vectors = [
        indexes / f'{repo}.vectors-{version}{suffix}.json'
        for repo in ('app', 'lib')
        for version in ('v1', 'v2')
        for suffix in ('', '.mlx')
    ]
    custom_vectors = [
        custom / f'{name}{suffix}.json' for name in ('base', 'enriched') for suffix in ('', '.mlx')
    ]
    for path in vectors + custom_vectors:
        path.write_text(
            json.dumps(
                {
                    'schema_version': 1,
                    'metadata': {'model_id': 'test', 'dimensions': 2, 'config_version': 'v1'},
                    'records': {},
                }
            )
        )
    keep = [
        indexes / 'unselected.chunks.json',
        indexes / 'reports' / 'requests.jsonl',
        indexes / '.conversations' / 'conversations.sqlite3',
        indexes / '.query_sessions' / 'session.json',
        indexes / '.gitkeep',
    ]
    for path in keep:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('keep')

    subprocess.run([*commands, 'clean'], cwd=ROOT, check=True, capture_output=True)
    assert all(not path.exists() for path in snapshots + vectors + custom_vectors)
    assert all(path.read_text() == 'keep' for path in keep)
    assert config.is_file()
    assert (root / 'app/example.py').is_file()

    subprocess.run([*commands, 'indexes'], cwd=ROOT, check=True, capture_output=True)
    assert all(path.is_file() for path in snapshots)


def test_make_clean_rejects_unrelated_custom_file_before_deleting(config):
    raw = json.loads(config.read_text())
    raw['retrieval'] = {'semantic_v1_store': 'notes.json'}
    config.write_text(json.dumps(raw))
    notes = config.parent / 'notes.json'
    notes.write_text('{"content":"keep"}')
    indexes = config.parent / 'indexes'
    indexes.mkdir()
    artifact = indexes / 'app.chunks.json'
    artifact.write_text('{}')

    result = subprocess.run(
        ['make', f'CONFIG={config}', f'PYTHON={sys.executable}', 'clean'],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode
    assert 'not a CodeTrace vector file' in result.stderr
    assert artifact.is_file()
    assert notes.read_text() == '{"content":"keep"}'
