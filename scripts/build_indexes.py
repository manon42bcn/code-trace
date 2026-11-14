"""Build chunks, relationships, and enabled local embeddings without Docker."""

from __future__ import annotations

import argparse
import json
import shlex
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_plan(config_path, selected=None, *, incremental=False):
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'))
    repositories = config.get('repositories')
    if not isinstance(repositories, dict) or not repositories:
        raise ValueError('config.json must contain a non-empty repositories object')
    requested = selected or list(repositories)
    names = []

    def include(name):
        if name not in repositories:
            raise ValueError(f'Repository not configured: {name}')
        if name in names:
            return
        names.append(name)
        relationship = config.get('relationships', {}).get(name, {})
        dependencies = (
            relationship if isinstance(relationship, list) else relationship.get('dependencies', [])
        )
        for dependency in dependencies:
            include(dependency)

    for name in requested:
        include(name)
    if str(ROOT / 'src') not in sys.path:
        sys.path.insert(0, str(ROOT / 'src'))
    from coderag.repository_paths import repository_index_path, repository_relationships_path
    from coderag.semantic_config import resolve_retrieval

    outputs = {}
    for name in names:
        settings = repositories[name]
        source = (config_path.parent / settings['path']).resolve()
        if not source.is_dir():
            raise ValueError(
                f'Repository {name}: source directory not found: {source}. '
                'Correct config.json or select repositories with --repo NAME.'
            )
        output = repository_index_path(config, config_path, name)
        if output in outputs:
            raise ValueError(
                f'Repositories {outputs[output]} and {name} share index output: {output}'
            )
        outputs[output] = name
    commands = []
    for name in names:
        command = ['-m', 'coderag', 'index', '--config', str(config_path), '--repo', name]
        if incremental:
            command.append('--incremental')
        commands.append(command)
    for name in names:
        commands.append(['-m', 'coderag', 'link', '--config', str(config_path), '--repo', name])
    # Resolve semantics with the same rules used by the query entry points.
    vector_outputs = set()
    for name in names:
        index_path = repository_index_path(config, config_path, name)
        _, paths, _ = resolve_retrieval(config, config_path, index_path)
        if paths is not None:
            for path in paths.values():
                if (
                    path in vector_outputs
                    or path in outputs
                    or path in {repository_relationships_path(config_path, repo) for repo in names}
                ):
                    raise ValueError(
                        f'Semantic output path is shared or overwrites another artifact: {path}'
                    )
                vector_outputs.add(path)
            commands.append(
                ['-m', 'coderag', 'embed', '--config', str(config_path), '--repo', name]
            )
    return commands


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument(
        '--repo',
        action='append',
        help='Select a repository (repeatable); dependencies are included',
    )
    parser.add_argument(
        '--incremental', action='store_true', help='Reuse unchanged files during indexing'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate paths and print the plan without writing indexes',
    )
    args = parser.parse_args(argv)
    try:
        commands = build_plan(args.config, args.repo, incremental=args.incremental)
        if not args.dry_run and any(command[2] == 'embed' for command in commands):
            import importlib.util

            if importlib.util.find_spec('sentence_transformers') is None:
                raise ValueError('Embedding dependencies missing; run make setup first')
        for position, command in enumerate(commands, 1):
            launch = [sys.executable, '-X', 'faulthandler', *command]
            print(  # noqa: T201 - CLI output
                f'[{position}/{len(commands)}] {shlex.join(launch)}', flush=True
            )
            if not args.dry_run:
                subprocess.run(launch, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        if exc.returncode < 0:
            number = -exc.returncode
            try:
                reason = f'{signal.Signals(number).name} ({number})'
            except ValueError:
                reason = f'signal {number}'
            message = f'Build command terminated by {reason}'
            exit_code = 128 + number
        else:
            message = f'Build command failed with exit code {exc.returncode}'
            exit_code = exc.returncode
        print(  # noqa: T201 - CLI diagnostics
            f'{message}: {shlex.join(exc.cmd)}. Earlier outputs are retained. '
            'Fix the error and rerun.',
            file=sys.stderr,
        )
        return exit_code
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)  # noqa: T201 - CLI output
        return 2
    if not args.dry_run:
        print('Preparation complete: selected repositories are ready to query.', flush=True)  # noqa: T201 - CLI output
    return 0


if __name__ == '__main__':
    sys.exit(main())
