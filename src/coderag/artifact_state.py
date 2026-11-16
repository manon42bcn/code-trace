"""Shared filesystem identity for index provenance and lightweight validation."""

from pathlib import Path


def file_stamp(path):
    stat = Path(path).stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def link_signature(config, repo):
    import hashlib
    import json

    selected = {}

    def include(name):
        if name in selected:
            return
        relation = config.get('relationships', {}).get(name, {})
        selected[name] = {
            'relationship': relation,
            'source_path': config.get('repositories', {}).get(name, {}).get('path'),
        }
        dependencies = relation if isinstance(relation, list) else relation.get('dependencies', [])
        for dependency in dependencies:
            include(dependency)

    include(repo)
    return hashlib.sha256(
        json.dumps(
            {'repositories': selected, 'analysis': config.get('analysis', {})}, sort_keys=True
        ).encode()
    ).hexdigest()
