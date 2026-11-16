"""Invoke an installed CodeTrace checkout from a portable skill configuration."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def resolve_path(value, base):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('configured paths must be non-empty strings')
    path = Path(value).expanduser()
    return (base / path).resolve()


def build_command(config_path, args):
    config_path = config_path.resolve()
    settings = json.loads(config_path.read_text(encoding='utf-8'))
    if not isinstance(settings, dict):
        raise ValueError('skill configuration must be an object')
    value = settings.get('code_trace_root', settings.get('code_rag_root'))
    root = resolve_path(value, config_path.parent)
    if 'code_trace_root' in settings and 'code_rag_root' in settings:
        if root != resolve_path(settings['code_rag_root'], config_path.parent):
            raise ValueError('Conflicting code_trace_root and legacy code_rag_root')
    if not (root / 'src' / 'codetrace' / '__main__.py').is_file():
        raise ValueError('code_trace_root must point to a checkout with codetrace query support')
    python = root / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
    if not python.is_file():
        raise ValueError(
            'CodeTrace virtual environment missing; run uv sync in code_trace_root first'
        )
    pipeline_path = root / 'config.json'
    pipeline = json.loads(pipeline_path.read_text(encoding='utf-8'))
    if not isinstance(pipeline, dict):
        raise ValueError('CodeTrace config.json must be an object')
    repo = settings.get('repo')
    repositories = pipeline.get('repositories', {})
    if not isinstance(repo, str) or repo not in repositories:
        raise ValueError(f'Repository not configured: {repo}; set repo in the skill configuration')
    command = [
        str(python),
        '-m',
        'codetrace',
        'query',
        args.query,
        '--default-repo',
        repo,
        '--config',
        str(pipeline_path),
        '--mode',
        'evidence',
        '--budget-profile',
        (
            'code-trace-inventory'
            if 'code-trace-inventory' in pipeline.get('query_profiles', {})
            or 'code-inventory' not in pipeline.get('query_profiles', {})
            else 'code-inventory'
        ),
    ]
    for key in ('limit', 'max_chunks', 'max_chars'):
        value = getattr(args, key)
        if value is not None:
            command += ['--' + key.replace('_', '-'), str(value)]
    for flag, values in (
        ('--file', args.file),
        ('--directory', args.directory),
        ('--source-type', args.source_type),
    ):
        for value in values or []:
            command += [flag, value]
    command += ['--readiness', args.readiness]
    if args.require_fresh:
        command.append('--require-fresh')
    if args.session_dir:
        command += ['--session-dir', str(args.session_dir.expanduser().resolve())]
    if args.session_ttl is not None:
        command += ['--session-ttl', str(args.session_ttl)]
    if args.no_session:
        command.append('--no-session')
    if args.retrieval_mode:
        command += ['--retrieval-mode', args.retrieval_mode]
    if args.page_size is not None:
        command += ['--page-size', str(args.page_size)]
    if args.cursor is not None:
        command += ['--cursor', args.cursor]
    if args.resolve_only:
        command.append('--resolve-only')
    if args.repo is not None:
        command += ['--repo', args.repo]
    if args.report:
        command += ['--report', str(args.report.resolve())]
    if args.allow_remote:
        command.append('--allow-remote')
    return command, root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('query')
    parser.add_argument(
        '--config', type=Path, default=Path(__file__).resolve().parents[1] / 'config.local.json'
    )
    parser.add_argument(
        '--resolve-only', action='store_true', help='Inspect repository routing without querying'
    )
    parser.add_argument('--retrieval-mode', choices=('configured', 'lexical', 'semantic'))
    parser.add_argument('--repo', help='Explicit configured repository selector')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--max-chunks', type=int)
    parser.add_argument('--max-chars', type=int)
    parser.add_argument('--file', action='append')
    parser.add_argument('--directory', action='append')
    parser.add_argument('--source-type', action='append')
    parser.add_argument('--page-size', type=int)
    parser.add_argument('--cursor')
    parser.add_argument('--session-dir', type=Path)
    parser.add_argument('--session-ttl', type=int)
    parser.add_argument('--no-session', action='store_true')
    parser.add_argument('--readiness', choices=('quick', 'full', 'off'), default='quick')
    parser.add_argument('--require-fresh', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--allow-remote', action='store_true')
    args = parser.parse_args(argv)
    try:
        command, root = build_command(args.config, args)
        # No shell, installation, index updates, or provider selection in the launcher.
        return subprocess.run(command, cwd=root).returncode
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(  # noqa: T201 - CLI output
            json.dumps(
                {
                    'schema_version': '1',
                    'status': 'error',
                    'mode': 'evidence',
                    'answer': None,
                    'claims': [],
                    'citations': [],
                    'evidence': [],
                    'limitations': [],
                    'error': {'type': type(exc).__name__, 'message': str(exc)},
                }
            )
        )
        return 2


if __name__ == '__main__':
    sys.exit(main())
