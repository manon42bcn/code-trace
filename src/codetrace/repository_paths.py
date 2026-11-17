"""Resolve repository artifacts consistently from the central configuration."""

from pathlib import Path


def index_output(config, repo):
    """Return the index filename derived exclusively from the repository identifier."""
    settings = config.get('repositories', {}).get(repo)
    if not isinstance(settings, dict):
        raise ValueError(f'Repository not configured: {repo}')
    if not repo or repo in {'.', '..'} or '/' in repo or '\\' in repo:
        raise ValueError('Repository names must be identifiers, not directory paths')
    if 'output' in settings:
        raise ValueError(
            f'Repository {repo}: remove output; filenames are derived from the repository name'
        )
    return f'indexes/{repo}.chunks.json'


def repository_index_path(config, config_path, repo):
    return (Path(config_path).resolve().parent / index_output(config, repo)).resolve()


def repository_relationships_path(config_path, repo):
    return Path(config_path).resolve().parent / 'indexes' / f'{repo}.relationships.json'


def _deps(config: dict, repo: str) -> list[str]:
    relationship = config.get('relationships', {}).get(repo, {})
    if isinstance(relationship, list):
        return relationship
    return relationship.get('dependencies', [])


def transitive_dependencies(config: dict, root: str) -> list[str]:
    """Return declared dependencies in depth-first order, visiting each once."""
    ordered = []
    seen = {root}

    def walk(node):
        for dep in _deps(config, node):
            if dep not in seen:
                seen.add(dep)
                ordered.append(dep)
                walk(dep)

    walk(root)
    return ordered
