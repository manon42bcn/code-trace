"""Validate JSON syntax, duplicate keys, and non-finite numbers without rewriting files."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate object key: {key!r}')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f'Non-standard JSON number: {value}')


def discover_files():
    """Include tracked and untracked JSON, respecting Git ignores and generated outputs."""
    result = subprocess.run(
        [
            'git',
            '-C',
            str(ROOT),
            'ls-files',
            '--cached',
            '--others',
            '--exclude-standard',
            '-z',
            '--',
            '*.json',
        ],
        capture_output=True,
        check=True,
    )
    paths = [
        Path(name.decode(sys.getfilesystemencoding()))
        for name in result.stdout.split(b'\0')
        if name
    ]
    return sorted({ROOT / path for path in paths if path.parts[0] not in {'indexes', 'dry_run'}})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'files', nargs='*', type=Path, help='Files to validate; otherwise discover repository JSON'
    )
    args = parser.parse_args(argv)
    try:
        files = args.files or discover_files()
    except (OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f'Error discovering JSON files: {exc}\n')
    failed = False
    for path in files:
        try:
            json.loads(
                path.read_text(encoding='utf-8'),
                object_pairs_hook=unique_object,
                parse_constant=reject_constant,
            )
        except (OSError, ValueError) as exc:
            print(f'{path}: {exc}', file=sys.stderr)  # noqa: T201 - CLI diagnostics
            failed = True
    if not failed:
        print(f'Validated {len(files)} JSON files.')  # noqa: T201 - CLI output
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
