"""Portable installations preserve local data and track only managed distributions."""

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/manage_skills.py'
spec = importlib.util.spec_from_file_location('manage_skills', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    source = tmp_path / 'checkout'
    for name in installer.NAMES:
        shutil.copytree(
            SCRIPT.parents[1] / 'skills' / name,
            source / 'skills' / name,
            ignore=shutil.ignore_patterns('config.local.json', '__pycache__'),
        )
    (source / 'pyproject.toml').write_text('[project]\nversion = "0.9.5"\n')
    (source / 'config.json').write_text('{"repositories": {"demo": {}, "other": {}}}')
    monkeypatch.setattr(installer, 'ROOT', source)
    registry = source / 'skills/installations.local.json'
    destination = tmp_path / 'consumer with spaces' / '.claude/skills'

    def args(command='install', **values):
        return argparse.Namespace(
            command=command,
            dest=destination if command == 'install' else None,
            repo='demo',
            skill=None,
            registry=registry,
            dry_run=False,
            adopt=False,
            overwrite_modified=False,
            **values,
        )

    def run(command='install', **values):
        options = args(command)
        for key, value in values.items():
            setattr(options, key, value)
        return installer.execute(options)

    return source, destination, registry, run


def test_install_both_records_files_and_absolute_configuration(environment):
    source, dest, registry, run = environment
    result, code = run()
    assert code == 0
    assert len(result['plans']) == 2
    records = installer.load_registry(registry)['installations']
    assert {r['skill'] for r in records} == set(installer.NAMES)
    for name in installer.NAMES:
        local = json.loads((dest / name / 'config.local.json').read_text())
        assert local == {'code_trace_root': str(source), 'repo': 'demo'}
        assert (dest / name / 'scripts/query.py').read_bytes() == (
            source / 'skills' / name / 'scripts/query.py'
        ).read_bytes()
    assert run('status')[1] == 0


def test_updates_preserve_configuration_bytes_and_unknown_files(environment):
    source, dest, _, run = environment
    run()
    local = dest / 'code-trace/config.local.json'
    local.write_bytes(b'{ "custom": true, "repo": "other" }\n')
    notes = dest / 'code-trace/my-notes.txt'
    notes.write_text('keep this')
    (source / 'skills/code-trace/SKILL.md').write_text('Updated instructions')
    (source / 'pyproject.toml').write_text('[project]\nversion = "0.9.6"\n')
    assert run('status')[0]['installations'][0]['outdated']
    run('update')
    assert local.read_bytes() == b'{ "custom": true, "repo": "other" }\n'
    assert notes.read_text() == 'keep this'
    assert (dest / 'code-trace/SKILL.md').read_text() == 'Updated instructions'


def test_modified_files_block_preflight_until_explicit_overwrite(environment):
    _, dest, registry, run = environment
    run()
    managed = dest / 'code-trace-inventory/scripts/query.py'
    managed.write_text('local customization')
    before = registry.read_bytes()
    assert run('status')[1] == 1
    with pytest.raises(ValueError, match='Locally modified'):
        run('update')
    assert registry.read_bytes() == before
    assert managed.read_text() == 'local customization'
    run('update', overwrite_modified=True)
    assert run('status')[1] == 0


def test_dry_run_does_not_create_destinations_or_registry(environment):
    _, dest, registry, run = environment
    result, code = run(dry_run=True)
    assert code == 0
    assert len(result['plans']) == 2
    assert not dest.exists()
    assert not registry.exists()


def test_adopt_manual_copy_preserves_local_config(environment):
    _, dest, registry, run = environment
    target = dest / 'code-trace'
    target.mkdir(parents=True)
    (target / 'SKILL.md').write_text('old version')
    (target / 'config.local.json').write_text('intentionally preserved bytes')
    with pytest.raises(ValueError, match='--adopt'):
        run(skill=['code-trace'])
    assert not registry.exists()
    run(skill=['code-trace'], adopt=True)
    assert (target / 'config.local.json').read_text() == 'intentionally preserved bytes'


def test_selection_update_and_missing_destination(environment):
    _, dest, _, run = environment
    run(skill=['code-trace'])
    assert not (dest / 'code-trace-inventory').exists()
    with pytest.raises(ValueError, match='No recorded'):
        run('update', skill=['code-trace-inventory'])
    shutil.rmtree(dest / 'code-trace')
    assert run('status')[0]['installations'][0]['status'] == 'missing'
    run('update')
    assert run('status')[1] == 0


def test_only_obsolete_managed_files_are_removed(environment):
    source, dest, _, run = environment
    obsolete = source / 'skills/code-trace/scripts/old.py'
    obsolete.write_text('old helper')
    run()
    (dest / 'code-trace/unknown.txt').write_text('not managed')
    obsolete.unlink()
    run('update')
    assert not (dest / 'code-trace/scripts/old.py').exists()
    assert (dest / 'code-trace/unknown.txt').exists()


def test_symlinks_and_source_overlap_are_rejected(environment):
    source, dest, _, run = environment
    with pytest.raises(ValueError, match='overlaps'):
        run(dest=source / 'skills')
    dest.mkdir(parents=True)
    (dest / 'code-trace').symlink_to(source / 'skills/code-trace', target_is_directory=True)
    with pytest.raises(ValueError, match='overlaps'):
        run()


def test_bad_registry_is_not_overwritten(environment):
    _, _, registry, run = environment
    registry.write_text('{"schema_version": 99}')
    with pytest.raises(ValueError, match='Invalid'):
        run()
    assert registry.read_text() == '{"schema_version": 99}'


def test_new_configuration_requires_valid_repo_and_source_local_config_is_not_copied(environment):
    source, dest, _, run = environment
    (source / 'skills/code-trace/config.local.json').write_text('do not distribute')
    with pytest.raises(ValueError, match='--repo'):
        run(repo='unknown')
    run()
    assert 'do not distribute' not in (dest / 'code-trace/config.local.json').read_text()


def test_registry_lock_prevents_overlapping_writers(environment):
    _, _, registry, _ = environment
    with installer.registry_lock(registry):
        with pytest.raises(ValueError, match='locked'):
            with installer.registry_lock(registry):
                pass
    assert not registry.with_name(registry.name + '.lock').exists()


def test_status_can_detect_manual_copy_in_explicit_directory(environment):
    _, dest, registry, run = environment
    (dest / 'code-trace').mkdir(parents=True)
    rows, code = run('status', dest=dest)
    assert code == 1
    assert rows['installations'][0]['status'] == 'unregistered'
    assert rows['installations'][0]['version'] is None
    assert not registry.exists()


def test_status_checks_preserved_configuration_without_rewriting_it(environment):
    _, dest, _, run = environment
    run()
    config = dest / 'code-trace/config.local.json'
    config.write_text('{"code_trace_root": "/other/checkout", "repo": "demo"}')
    result, code = run('status')
    assert code == 1
    assert result['installations'][0]['configuration_status'] == 'other_checkout'
    before = config.read_bytes()
    run('update')
    assert config.read_bytes() == before


def test_registry_cannot_replace_configuration_inside_target(environment):
    _, dest, _, run = environment
    with pytest.raises(ValueError, match='outside'):
        run(registry=dest / 'code-trace/config.local.json')
    assert not dest.exists()


def test_cli_dry_run_and_lock_cleanup(environment, capsys):
    _, dest, registry, _ = environment
    code = installer.main(
        ['install', '--dest', str(dest), '--repo', 'demo', '--registry', str(registry), '--dry-run']
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)['dry_run']
    assert not registry.exists()
    code = installer.main(
        ['install', '--dest', str(dest), '--repo', 'demo', '--registry', str(registry)]
    )
    assert code == 0
    assert len(json.loads(capsys.readouterr().out)['plans']) == 2
    assert not registry.with_name(registry.name + '.lock').exists()


def test_installed_skills_resolve_using_checkout_environment(environment, tmp_path):
    source, dest, _, run = environment
    (source / 'src').symlink_to(SCRIPT.parents[1] / 'src', target_is_directory=True)
    (source / '.venv').symlink_to(Path(sys.prefix), target_is_directory=True)
    run()
    for name in installer.NAMES:
        proc = subprocess.run(
            [sys.executable, str(dest / name / 'scripts/query.py'), 'order_id', '--resolve-only'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        result = json.loads(proc.stdout)
        assert result['routing_only']
        assert result['repository'] == 'demo'
        assert result['answer'] is None


def declare(source, entries):
    path = source / 'config.json'
    raw = json.loads(path.read_text())
    raw['skills'] = {'installations': entries}
    path.write_text(json.dumps(raw))


def entry(destination, repo='demo', names=None):
    return {'destination': str(destination), 'repo': repo, 'names': names or list(installer.NAMES)}


def test_declared_batch_generates_configs_and_tracks_drift(environment):
    source, dest, registry, run = environment
    other = source / 'relative-consumer/.agents/skills'
    declare(
        source, [entry(dest), entry('relative-consumer/.agents/skills', 'other', ['code-trace'])]
    )
    preview, _ = run(dest=None, repo=None, dry_run=True)
    assert len(preview['plans']) == 3
    assert not registry.exists()
    assert not dest.exists()
    assert run('status', repo=None)[1] == 1
    run(dest=None, repo=None)
    assert json.loads((other / 'code-trace/config.local.json').read_text())['repo'] == 'other'
    assert run('status', repo=None)[1] == 0
    declare(source, [entry(dest, 'other')])
    status, code = run('status', repo=None)
    assert code == 1
    assert any(
        row.get('configuration_status') == 'configuration_drift' for row in status['installations']
    )
    run('update', repo=None)
    assert json.loads((dest / 'code-trace/config.local.json').read_text())['repo'] == 'other'
    assert (other / 'code-trace/SKILL.md').exists()  # Removing a declaration never uninstalls.
    assert any(not row['declared'] for row in run('status', repo=None)[0]['installations'])


def test_declared_config_local_edits_require_explicit_overwrite(environment):
    source, dest, _, run = environment
    declare(source, [entry(dest)])
    run(dest=None, repo=None)
    local = dest / 'code-trace/config.local.json'
    local.write_text('{"repo": "other", "custom": true}')
    with pytest.raises(ValueError, match='configuration'):
        run('update', repo=None)
    assert json.loads(local.read_text())['custom']
    run('update', repo=None, overwrite_modified=True)
    assert json.loads(local.read_text()) == {'code_trace_root': str(source), 'repo': 'demo'}


def test_declared_selection_and_explicit_overrides(environment):
    source, dest, _, run = environment
    declare(source, [entry(dest)])
    run(dest=None, repo='other', skill=['code-trace-inventory'])
    assert not (dest / 'code-trace').exists()
    assert (
        json.loads((dest / 'code-trace-inventory/config.local.json').read_text())['repo'] == 'other'
    )
    manual = source / 'manual'
    run(dest=manual, repo='demo', skill=['code-trace'])
    assert (manual / 'code-trace').is_dir()
    assert not (dest / 'code-trace').exists()


@pytest.mark.parametrize(
    'entries',
    [
        [entry('/tmp/skills', repo='unknown')],
        [entry('/tmp/skills', names=['unsupported'])],
        [entry('')],
        [entry('/tmp/skills'), entry('/tmp/skills')],
        [{'destination': '/tmp/skills', 'repo': 'demo'}],
        'invalid',
    ],
)
def test_invalid_declarations_do_not_write(environment, entries):
    source, dest, registry, run = environment
    declare(source, entries)
    with pytest.raises(ValueError, match=r'Skill|skill|Duplicate|requires'):
        run(dest=None, repo=None)
    assert not dest.exists()
    assert not registry.exists()


def test_declared_preflight_checks_all_destinations_before_writing(environment):
    source, dest, registry, run = environment
    conflict = source / 'conflict'
    (conflict / 'code-trace').mkdir(parents=True)
    (conflict / 'code-trace/SKILL.md').write_text('manual instructions')
    declare(source, [entry(dest), entry(conflict)])
    with pytest.raises(ValueError, match='Unregistered'):
        run(dest=None, repo=None)
    assert not dest.exists()
    assert not registry.exists()


def test_empty_declarations_preserve_installed_copies(environment):
    source, dest, registry, run = environment
    run()
    before = registry.read_bytes()
    declare(source, [])
    result, _ = run('update', repo=None)
    assert result['plans'] == []
    assert registry.read_bytes() == before
    assert (dest / 'code-trace/SKILL.md').exists()


def test_cli_uses_central_declarations_without_dest(environment, capsys):
    source, dest, registry, _ = environment
    declare(source, [entry(dest)])
    assert installer.main(['install', '--registry', str(registry), '--dry-run']) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result['plans']) == 2
    assert all(plan['config_action'] == 'create' for plan in result['plans'])
    assert not dest.exists()
    assert not registry.exists()


def test_installs_include_managed_examples_and_ignore_local_configuration(environment):
    source, dest, registry, run = environment
    run()
    for name in installer.NAMES:
        assert (dest / name / 'config.example.json').read_bytes() == (
            source / 'skills' / name / 'config.example.json'
        ).read_bytes()
        assert (dest / name / 'config.local.json').is_file()
        assert 'config.local.json' in (dest / name / '.gitignore').read_text()
    assert all(
        'config.example.json' in record['files'] and 'config.local.json' not in record['files']
        for record in installer.load_registry(registry)['installations']
    )


def test_updates_synchronize_examples_without_changing_local_configuration(environment):
    source, dest, _, run = environment
    run()
    local = (dest / 'code-trace/config.local.json').read_bytes()
    example = source / 'skills/code-trace/config.example.json'
    example.write_text('{"code_trace_root": "/new/example/path", "repo": "demo"}')
    run('update')
    assert (dest / 'code-trace/config.example.json').read_bytes() == example.read_bytes()
    assert (dest / 'code-trace/config.local.json').read_bytes() == local


def test_updates_restore_examples_omitted_by_previous_version(environment):
    source, dest, registry, run = environment
    run()
    data = installer.load_registry(registry)
    for record in data['installations']:
        (Path(record['path']) / 'config.example.json').unlink()
        record['files'].pop('config.example.json')
    registry.write_text(json.dumps(data))
    run('update')
    for name in installer.NAMES:
        assert (dest / name / 'config.example.json').read_bytes() == (
            source / 'skills' / name / 'config.example.json'
        ).read_bytes()


def test_modified_examples_block_updates_until_reviewed(environment):
    _, dest, _, run = environment
    run()
    example = dest / 'code-trace/config.example.json'
    example.write_text('user changes')
    with pytest.raises(ValueError, match='Locally modified'):
        run('update')
    assert example.read_text() == 'user changes'
    run('update', overwrite_modified=True)
    assert example.read_text() != 'user changes'
