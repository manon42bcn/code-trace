"""Read local Git provenance without fetching, hooks, optional locks or repository execution."""

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')
    return subprocess.run(
        [
            'git',
            '--no-pager',
            '--no-optional-locks',
            '-c',
            'core.fsmonitor=false',
            '-C',
            str(root),
            *args,
        ],
        capture_output=True,
        env=env,
        timeout=5,
        check=False,
    )


def capture_git(root):
    """Capture the enclosing worktree, including subdirectories and linked worktrees."""
    result = {'captured_at': datetime.now(timezone.utc).isoformat()}
    try:
        top = git(root, 'rev-parse', '--show-toplevel')
        if top.returncode:
            # A .git marker with a failing probe is not a verified non-Git directory.
            marker = any((parent / '.git').exists() for parent in [Path(root), *Path(root).parents])
            return {**result, 'status': 'unavailable' if marker else 'not_repository'}
        head = git(root, 'rev-parse', '--verify', 'HEAD')
        branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
        filters = git(
            root,
            'config',
            '--null',
            '--name-only',
            '--get-regexp',
            r'^filter\..*\.(clean|smudge|process|required)$',
        )
        if filters.returncode not in {0, 1}:
            return {**result, 'status': 'unavailable'}
        overrides = []
        for key in filters.stdout.decode(errors='replace').split('\0'):
            if key:
                value = 'false' if key.endswith('.required') else ''
                overrides.extend(['-c', key + '=' + value])
        status = git(
            root,
            *overrides,
            '-c',
            'status.submoduleSummary=false',
            'status',
            '--porcelain=v1',
            '-z',
            '--untracked-files=normal',
            '--ignore-submodules=all',
        )
        if status.returncode or branch.returncode not in {0, 1}:
            return {**result, 'status': 'unavailable'}
        return {
            **result,
            'status': 'available',
            'commit': head.stdout.decode().strip() if head.returncode == 0 else None,
            'branch': branch.stdout.decode(errors='replace').strip()
            if branch.returncode == 0
            else None,
            'dirty': bool(status.stdout),
        }
    except (OSError, subprocess.TimeoutExpired):
        return {**result, 'status': 'unavailable'}


def indexed_git(before, after):
    return {
        **after,
        'start_commit': before.get('commit'),
        'reference_stable': before.get('status') == after.get('status') == 'available'
        and before.get('commit') == after.get('commit')
        and before.get('branch') == after.get('branch'),
    }


def compare_git(root, indexed):
    current = capture_git(root)
    if not isinstance(indexed, dict):
        indexed = None
    result = {
        'indexed': indexed,
        'current': current,
        'reference_changed': False,
        'relation': 'unknown',
        'ahead': None,
        'behind': None,
    }
    if current['status'] == 'not_repository' and (
        indexed is None or indexed.get('status') == 'not_repository'
    ):
        return {**result, 'status': 'not_applicable', 'message': 'Source is not a Git worktree.'}
    if current['status'] != 'available' or not indexed or indexed.get('status') != 'available':
        return {
            **result,
            'status': 'unknown',
            'message': 'Git provenance unavailable; reindex legacy artifacts or check local Git.',
        }
    old_commit = indexed.get('commit')
    if old_commit is not None and (
        not isinstance(old_commit, str)
        or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', old_commit)
    ):
        return {**result, 'status': 'unknown', 'message': 'Invalid indexed Git commit provenance.'}
    stable = indexed.get('reference_stable', False)
    old, new = indexed.get('commit'), current.get('commit')
    changed = old != new or indexed.get('branch') != current.get('branch')
    result.update(reference_changed=changed)
    if old == new:
        result.update(relation='same_commit' if old else 'unborn', ahead=0, behind=0)
    elif old and new:
        try:
            counts = git(root, 'rev-list', '--left-right', '--count', f'{old}...{new}', '--')
            if counts.returncode == 0:
                behind, ahead = map(int, counts.stdout.split())
                result.update(
                    behind=behind,
                    ahead=ahead,
                    relation='ahead' if not behind else 'behind' if not ahead else 'diverged',
                )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    warning = changed or current['dirty'] or indexed.get('dirty') or not stable or old is None
    return {
        **result,
        'status': 'changed' if warning else 'current',
        'message': 'Git reference/worktree differs or snapshot was not a clean pinned commit; '
        'source verification determines whether an update is needed.'
        if warning
        else 'Indexed and current clean Git references match.',
    }
