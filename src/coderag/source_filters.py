"""Repository-relative source scopes shared by retrieval and context construction."""

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from .core import EXT, SPECIAL

SOURCE_TYPES = tuple(sorted(set(EXT.values()) | set(SPECIAL.values())))


def relative_path(value, *, directory=False):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('Source filters require repository-relative POSIX paths')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or (str(path) == '.' and not directory):
        raise ValueError('Source filters cannot use absolute paths or parent traversal')
    return path.as_posix()


@dataclass(frozen=True)
class SourceFilters:
    files: tuple[str, ...] = ()
    directories: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()

    def __post_init__(self):
        for key in ('files', 'directories', 'source_types'):
            value = getattr(self, key)
            if not isinstance(value, (list, tuple)):
                raise ValueError(f'{key} must be a list of strings')
            if key == 'source_types':
                if any(item not in SOURCE_TYPES for item in value):
                    raise ValueError(f'Unknown source type; choose from {SOURCE_TYPES}')
                normalized = value
            else:
                normalized = [relative_path(item, directory=key == 'directories') for item in value]
            object.__setattr__(self, key, tuple(sorted(set(normalized))))

    @property
    def active(self):
        return bool(self.files or self.directories or self.source_types)

    def matches(self, chunk):
        path = chunk.get('path', '')
        if not isinstance(path, str) or not path:
            return False
        return (
            (not self.files or path in self.files)
            and (
                not self.directories
                or any(
                    directory == '.' or path.startswith(directory + '/')
                    for directory in self.directories
                )
            )
            and (not self.source_types or chunk.get('language') in self.source_types)
        )

    def describe(self):
        return {key: list(value) for key, value in asdict(self).items()}


def scope_sources(index, graph, filters):
    """Prune chunk-bearing nodes/edges too, keeping structural expansion inside the scope."""
    if filters is None or not filters.active:
        return index, graph
    chunks = [chunk for chunk in index.get('chunks', []) if filters.matches(chunk)]
    ids = {chunk['id'] for chunk in chunks}
    paths = {chunk.get('path') for chunk in chunks}
    nodes = [
        node
        for node in graph.get('nodes', [])
        if (
            node.get('chunk_id') in ids
            or (node.get('chunk_id') is None and (not node.get('path') or node['path'] in paths))
        )
    ]
    node_ids = {node['id'] for node in nodes}
    edges = [
        edge
        for edge in graph.get('edges', [])
        if edge.get('source') in node_ids and edge.get('target') in node_ids
    ]
    return {**index, 'chunks': chunks}, {**graph, 'nodes': nodes, 'edges': edges}
