"""Interactive terminal interface for the answer command."""

import argparse
import json
import shlex
import sys
from pathlib import Path


def run(argv, run_command):
    parser = argparse.ArgumentParser(prog='codetrace interactive')
    parser.add_argument('--config', type=Path, default=Path('config.json'))
    parser.add_argument('--repo', required=True)
    parser.add_argument('--allow-remote', action='store_true')
    args = parser.parse_args(argv)
    config = args.config.resolve()

    try:
        repositories = json.loads(config.read_text(encoding='utf-8'))['repositories']
        if not isinstance(repositories, dict) or args.repo not in repositories:
            raise ValueError(f'Repository not configured: {args.repo}')
    except (OSError, KeyError, ValueError, TypeError) as exc:
        parser.exit(2, f'Error: {exc}\n')

    repo = args.repo
    sys.stdout.write('Use /repos to list repositories, --repo NAME to switch, or --exit to quit.\n')
    try:
        while True:
            question = input(f'Ask your question about {repo}> ').strip()
            if not question:
                continue
            command = question.split(maxsplit=1)[0]
            if command in {'codetrace', 'code-trace', '--repo', '--exit', '/repos', '/exit'}:
                try:
                    parts = shlex.split(question)
                except ValueError as exc:
                    sys.stderr.write(f'Error: {exc}\n')
                    continue
                if command in {'codetrace', 'code-trace'}:
                    parts = parts[1:]
                if parts in (['--exit'], ['/exit']):
                    return 0
                if parts == ['/repos']:
                    sys.stdout.write('\n'.join(sorted(repositories)) + '\n')
                elif len(parts) == 2 and parts[0] == '--repo':
                    if parts[1] in repositories:
                        repo = parts[1]
                    else:
                        sys.stderr.write(f'Unknown repository: {parts[1]}\n')
                else:
                    sys.stderr.write('Use --repo NAME, /repos, or --exit.\n')
                continue
            try:
                run_command(
                    [
                        'answer',
                        '--config',
                        str(config),
                        '--repo',
                        repo,
                        '--output-format',
                        'text',
                        *(['--allow-remote'] if args.allow_remote else []),
                        '--',
                        question,
                    ]
                )
            except SystemExit as exc:
                if exc.code != 2:
                    raise
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write('\n')
        return 0
