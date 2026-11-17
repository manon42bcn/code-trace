"""Shared filesystem identity for index provenance and lightweight validation."""

from pathlib import Path

from .repository_paths import transitive_dependencies


def file_stamp(path):
    stat = Path(path).stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def link_signature(config, repo):
    import hashlib
    import json

    repositories = config.get('repositories', {})
    relationships = config.get('relationships', {})
    selected = {
        name: {
            'relationship': relationships.get(name, {}),
            'source_path': repositories.get(name, {}).get('path'),
            'framework': repositories.get(name, {}).get('framework'),
        }
        for name in (repo, *transitive_dependencies(config, repo))
    }
    return hashlib.sha256(
        json.dumps(
            {'repositories': selected, 'analysis': config.get('analysis', {})}, sort_keys=True
        ).encode()
    ).hexdigest()
