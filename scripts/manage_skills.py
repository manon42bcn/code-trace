"""Install, track and update portable CodeTrace skills while preserving local configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('code-trace', 'code-trace-inventory')
REGISTRY = ROOT / 'skills/installations.local.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version():
    project = (ROOT / 'pyproject.toml').read_text(encoding='utf-8').split('[project]', 1)[1]
    return re.search(r'^version\s*=\s*"([^"]+)"', project, re.MULTILINE)[1]


def distribution(name):
    source = ROOT / 'skills' / name
    files = {}
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
            if relative.as_posix() != '.gitignore':
                continue
        if path.name == 'config.local.json' or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError(f'Skill distribution must not contain symlinks: {path}')
        if path.is_file():
            files[relative.as_posix()] = sha(path)
    if not {'SKILL.md', 'scripts/query.py', 'config.example.json'} <= files.keys():
        raise ValueError(f'Incomplete skill distribution: {name}')
    return files


def load_registry(path):
    if not path.exists():
        return {'schema_version': 1, 'installations': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ValueError('Invalid installation registry')
    records = data.get('installations')
    if not isinstance(records, list):
        raise ValueError('Invalid registry installations')
    seen = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get('skill') not in NAMES
            or not isinstance(record.get('path'), str)
            or not Path(record['path']).is_absolute()
            or not isinstance(record.get('files'), dict)
        ):
            raise ValueError('Invalid installation record')
        if Path(record['path']).name != record['skill']:
            raise ValueError('Recorded path must end with the skill name')
        if record['path'] in seen:
            raise ValueError('Duplicate installation destination')
        seen.add(record['path'])
        for relative in record['files']:
            validate_relative(relative)
    return data


def validate_relative(relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or relative == 'config.local.json':
        raise ValueError('Invalid managed file path')
    if not path.parts or relative in {'.', ''}:
        raise ValueError('Invalid managed file path')


def safe_path(target, relative):
    validate_relative(relative)
    path = target / relative
    if target.is_symlink() or any(
        parent.is_symlink()
        for parent in [path, *path.parents]
        if parent == target or target in parent.parents
    ):
        raise ValueError(f'Symlink in managed destination: {path}')
    return path


def atomic_write(path, content, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def registry_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + '.lock')
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            f'Installer already locked: {lock}; remove only if no installer is running.'
        ) from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def plan_install(
    name, target, record, *, repo=None, adopt=False, overwrite=False, configured=False
):
    """Preflight every managed file before touching an installation."""
    target = target.absolute()
    source = ROOT / 'skills' / name
    resolved = target.resolve()
    if (
        resolved == source
        or resolved in source.parents
        or source in resolved.parents
        or any(resolved == ROOT / 'skills' / other for other in NAMES)
    ):
        raise ValueError('Destination overlaps the source skill distribution')
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError(f'Skill destination must be a regular directory: {target}')
    files = distribution(name)
    previous = record['files'] if record else {}
    actions = []
    for relative in sorted(files.keys() | previous.keys()):
        path = safe_path(target, relative)
        if path.exists() and not path.is_file():
            raise ValueError(f'Managed destination is not a file: {path}')
        current = sha(path) if path.is_file() else None
        desired = files.get(relative)
        if current == desired:
            continue
        if current is not None:
            changed = current != previous.get(relative)
            if record and changed and not overwrite:
                raise ValueError(
                    f'Locally modified file: {path}; review or use --overwrite-modified.'
                )
            if not record and not adopt:
                raise ValueError(
                    f'Unregistered existing skill: {target}; use install --adopt after review.'
                )
        actions.append({'file': relative, 'action': 'write' if desired else 'remove'})
    settings = target / 'config.local.json'
    configuration = None
    config_action = 'preserve'
    config_sha = record.get('config_sha') if record else None
    if configured or (not settings.exists() and not settings.is_symlink()):
        catalog = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))['repositories']
        if repo not in catalog:
            raise ValueError(
                'New local configuration requires --repo matching code_trace_root/config.json.'
            )
        desired = {'code_trace_root': str(ROOT), 'repo': repo}
        if configured and settings.is_symlink():
            raise ValueError(f'Managed local configuration cannot be a symlink: {settings}')
        if settings.exists():
            current_sha = sha(settings)
            try:
                matches = json.loads(settings.read_text(encoding='utf-8')) == desired
            except ValueError:
                matches = False
            if not matches:
                if current_sha != config_sha and not overwrite:
                    raise ValueError(
                        f'Locally modified/unmanaged configuration: {settings}; '
                        'review or use --overwrite-modified.'
                    )
                configuration = desired
                config_action = 'update'
            else:
                config_sha = current_sha
        else:
            configuration = desired
            config_action = 'create'
        if configuration is not None:
            config_sha = hashlib.sha256(
                (json.dumps(configuration, indent=2) + '\n').encode()
            ).hexdigest()
    return {
        'skill': name,
        'path': str(target),
        'version': version(),
        'files': files,
        'actions': actions,
        'configuration': configuration,
        'config_action': config_action,
        'config_sha': config_sha,
    }


def apply_plan(plan, registry):
    target = Path(plan['path'])
    for action in plan['actions']:
        destination = safe_path(target, action['file'])
        if action['action'] == 'remove':
            destination.unlink(missing_ok=True)
        else:
            source = ROOT / 'skills' / plan['skill'] / action['file']
            atomic_write(destination, source.read_bytes(), source.stat().st_mode & 0o777)
    if plan['configuration'] is not None:
        target.mkdir(parents=True, exist_ok=True)
        settings = target / 'config.local.json'
        content = json.dumps(plan['configuration'], indent=2) + '\n'
        if plan['config_action'] == 'update':
            atomic_write(settings, content.encode(), 0o600)
        else:
            # Exclusive creation preserves a configuration created after preflight.
            with settings.open('x', encoding='utf-8') as stream:
                stream.write(content)
    previous = next((r for r in registry['installations'] if r['path'] == str(target)), {})
    now = datetime.now(timezone.utc).isoformat()
    record = {
        'skill': plan['skill'],
        'path': str(target),
        'version': plan['version'],
        'source_root': str(ROOT),
        'files': plan['files'],
        'config_sha': plan['config_sha'],
        'installed_at': previous.get('installed_at', now),
        'updated_at': now,
    }
    registry['installations'] = [r for r in registry['installations'] if r['path'] != str(target)]
    registry['installations'].append(record)


def configuration_status(target):
    path = target / 'config.local.json'
    if not path.is_file():
        return 'missing'
    try:
        settings = json.loads(path.read_text(encoding='utf-8'))
        root = settings.get('code_trace_root', settings.get('code_rag_root'))
        if not isinstance(root, str) or not root.strip():
            return 'invalid'
        root = (path.resolve().parent / Path(root).expanduser()).resolve()
        if root != ROOT.resolve():
            return 'other_checkout'
        catalog = json.loads((root / 'config.json').read_text(encoding='utf-8'))['repositories']
        return 'configured' if settings.get('repo') in catalog else 'invalid'
    except (OSError, ValueError, KeyError, TypeError):
        return 'invalid'


def status_record(record):
    target = Path(record['path'])
    current_files = distribution(record['skill'])
    missing, modified = [], []
    for relative, expected in record['files'].items():
        path = safe_path(target, relative)
        if not path.is_file():
            missing.append(relative)
        elif sha(path) != expected:
            modified.append(relative)
    outdated = record.get('version') != version() or record['files'] != current_files
    return {
        **{k: record.get(k) for k in ('skill', 'path', 'version', 'installed_at', 'updated_at')},
        'available_version': version(),
        'outdated': outdated,
        'missing': missing,
        'modified': modified,
        'config_present': (target / 'config.local.json').exists(),
        'configuration_status': configuration_status(target),
        'status': 'missing'
        if not target.is_dir()
        else 'modified'
        if modified
        else 'incomplete'
        if missing
        else 'outdated'
        if outdated
        else 'current',
    }


def configured_installations(args):
    """Read desired destinations; explicit --dest keeps the manual workflow."""
    if args.dest is not None:
        return None
    path = ROOT / 'config.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    if 'skills' not in raw:
        return None
    section = raw['skills']
    if not isinstance(section, dict) or set(section) - {'installations'}:
        raise ValueError('skills must contain only installations')
    entries = section.get('installations')
    if not isinstance(entries, list):
        raise ValueError('skills.installations must be a list')
    if args.repo is not None and args.repo not in raw.get('repositories', {}):
        raise ValueError('Skill --repo must name a configured repository')
    selected, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'destination', 'repo', 'names'}:
            raise ValueError('Each skill installation requires destination, repo and names')
        destination, repo, names = entry['destination'], entry['repo'], entry['names']
        if not isinstance(destination, str) or not destination.strip():
            raise ValueError('Skill destination must be a nonempty path')
        if not isinstance(repo, str) or repo not in raw.get('repositories', {}):
            raise ValueError('Skill repo must name a configured repository')
        if not isinstance(names, list) or not names or any(name not in NAMES for name in names):
            raise ValueError('Skill names must be a nonempty list of supported names')
        parent = (path.parent / Path(destination).expanduser()).resolve()
        for name in names:
            target = parent / name
            if str(target) in seen:
                raise ValueError(f'Duplicate configured skill destination: {target}')
            seen.add(str(target))
            if args.skill is None or name in args.skill:
                selected.append((name, target, args.repo or repo))
    return selected


def execute(args):
    registry = load_registry(args.registry)
    desired = configured_installations(args)
    names = list(dict.fromkeys(args.skill or NAMES))
    records = [
        r
        for r in registry['installations']
        if r['skill'] in names and (args.dest is None or Path(r['path']).parent == args.dest)
    ]
    if args.command == 'status':
        rows = [status_record(record) for record in records]
        if desired is not None:
            expected = {str(target): repo for _, target, repo in desired}
            for row in rows:
                row['declared'] = row['path'] in expected
                if row['declared']:
                    row['desired_repo'] = expected[row['path']]
                    settings = Path(row['path']) / 'config.local.json'
                    try:
                        local = json.loads(settings.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        local = {}
                    row['configuration_matches'] = local == {
                        'code_trace_root': str(ROOT),
                        'repo': expected[row['path']],
                    }
                    record = next(r for r in records if r['path'] == row['path'])
                    if record.get('config_sha') and settings.is_file():
                        row['configuration_modified'] = sha(settings) != record['config_sha']
                    if not row['configuration_matches']:
                        row['configuration_status'] = 'configuration_drift'
            known = {row['path'] for row in rows}
            for name, target, repo in desired:
                if str(target) not in known:
                    rows.append(
                        {
                            'skill': name,
                            'path': str(target),
                            'desired_repo': repo,
                            'declared': True,
                            'status': 'unregistered' if target.exists() else 'not_installed',
                            'configuration_status': configuration_status(target),
                        }
                    )
        if args.dest:
            known = {row['path'] for row in rows}
            for name in names:
                target = args.dest / name
                if str(target) not in known and (target.exists() or target.is_symlink()):
                    rows.append(
                        {
                            'skill': name,
                            'path': str(target),
                            'version': None,
                            'available_version': version(),
                            'status': 'unregistered',
                            'configuration_status': configuration_status(target),
                        }
                    )
        return {'schema_version': 1, 'registry': str(args.registry), 'installations': rows}, (
            1
            if any(
                row['status'] != 'current' or row['configuration_status'] != 'configured'
                for row in rows
            )
            else 0
        )
    if desired is not None:
        plans = [
            plan_install(
                name,
                target,
                next((r for r in registry['installations'] if r['path'] == str(target)), None),
                repo=repo,
                configured=True,
                adopt=args.adopt,
                overwrite=args.overwrite_modified,
            )
            for name, target, repo in desired
        ]
    elif args.command == 'install':
        if args.dest is None:
            raise ValueError('install requires --dest (the parent skills directory)')
        plans = []
        for name in names:
            target = args.dest / name
            record = next((r for r in registry['installations'] if r['path'] == str(target)), None)
            plans.append(
                plan_install(
                    name,
                    target,
                    record,
                    repo=args.repo,
                    adopt=args.adopt,
                    overwrite=args.overwrite_modified,
                )
            )
    else:
        if not records:
            raise ValueError(
                'No recorded installations selected; register them with install first.'
            )
        plans = [
            plan_install(
                r['skill'], Path(r['path']), r, repo=args.repo, overwrite=args.overwrite_modified
            )
            for r in records
        ]
    if any(
        args.registry == Path(plan['path']) or Path(plan['path']) in args.registry.parents
        for plan in plans
    ):
        raise ValueError('Registry must be outside the installed skill directories')
    if not args.dry_run:
        for plan in plans:
            apply_plan(plan, registry)
            atomic_write(args.registry, (json.dumps(registry, indent=2) + '\n').encode())
    return {
        'schema_version': 1,
        'registry': str(args.registry),
        'dry_run': args.dry_run,
        'plans': [
            {k: v for k, v in plan.items() if k not in {'configuration', 'files'}} for plan in plans
        ],
    }, 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('command', choices=('install', 'update', 'status'))
    parser.add_argument('--dest', type=Path, help='Parent directory for installed skill folders')
    parser.add_argument('--skill', action='append', choices=NAMES)
    parser.add_argument(
        '--repo',
        help='Override declared repo; manual installations use it only for new configuration',
    )
    parser.add_argument('--registry', type=Path, default=REGISTRY)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument(
        '--adopt', action='store_true', help='Register/replace an existing manual copy'
    )
    parser.add_argument('--overwrite-modified', action='store_true')
    args = parser.parse_args(argv)
    args.registry = args.registry.expanduser().resolve()
    protected = [ROOT / 'pyproject.toml', ROOT / 'config.json', Path(__file__).resolve()]
    if args.registry in protected or any(
        (ROOT / 'skills' / name) in args.registry.parents for name in NAMES
    ):
        parser.error('Registry must not replace source/configuration files')
    if args.command != 'install' and args.adopt:
        parser.error('--adopt applies only to install')
    if args.dest:
        # Resolve the parent only; never hide a symlink at an individual skill destination.
        args.dest = args.dest.expanduser().resolve()
    try:
        if args.command == 'status' or args.dry_run:
            result, code = execute(args)
        else:
            with registry_lock(args.registry):
                result, code = execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))  # noqa: T201 - CLI output
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)  # noqa: T201
        code = 2
    return code


if __name__ == '__main__':
    sys.exit(main())
