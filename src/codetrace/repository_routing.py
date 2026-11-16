"""Conservative local repository selection from configured names and metadata."""

from __future__ import annotations

import re
import unicodedata

STOPWORDS = frozenset(
    'a an and de del el en for in la las los of on para por repository repositorio '
    'repo project proyecto sobre the un una y'.split()
)
PREFIX = re.compile(
    r'^\s*[¿?]?\s*(?:en|in|sobre)\s+(?P<selector>[^,:?\n]{1,160})[,\uFF1A:]\s*(?P<query>.+)$',
    re.IGNORECASE | re.DOTALL,
)


class RepositoryRoutingError(ValueError):
    def __init__(self, code, message, candidates=()):
        super().__init__(message)
        self.code = code
        self.candidates = sorted(candidates)


def tokens(text):
    return [
        ''.join(
            char
            for char in unicodedata.normalize('NFKD', match.group().casefold())
            if not unicodedata.combining(char)
        )
        for match in re.finditer(r'[^\W_]+', text)
    ]


# Embedded directives are metadata only at the end of an unquoted question.
REPO_SUFFIX = re.compile(r'(?<!\S)--repo(?:[ \t]+|=)([\w.-]+)[ \t]*$')
QUOTED = re.compile(r"`[^`\n]*`|'[^'\n]*'|\"[^\"\n]*\"")
SCOPE_BEFORE = re.compile(
    r'\b(?:en|in|sobre)\s+(?:(?:el|the)\s+)?'
    r'(?:(?:repo|repositorio|repository|proyecto|project)\s+)?$',
    re.IGNORECASE,
)


def protected(text, position):
    return any(match.start() <= position < match.end() for match in QUOTED.finditer(text))


def extract_repo_selector(query):
    selected = None
    while (match := REPO_SUFFIX.search(query)) and not protected(query, match.start()):
        if selected is not None and selected != match[1]:
            raise RepositoryRoutingError(
                'conflicting_repository', 'Conflicting --repo selectors.', [selected, match[1]]
            )
        selected = match[1]
        query = query[: match.start()].rstrip()
    if not query.strip() and selected is not None:
        raise ValueError('A repository selector requires a nonempty question')
    if re.search(r'(?<!\S)--repo(?:=)?\s*$', query) and not protected(query, query.rfind('--repo')):
        raise ValueError('--repo requires a repository name')
    return query, selected


def remove_repository_scope(query, matches, positions):
    """Remove explicit en/in/sobre selectors; preserve identifiers used as subject matter."""
    spans = []
    for start, end, name, reason, label in matches:
        left, right = positions[start].start(), positions[end - 1].end()
        if protected(query, left):
            continue
        prefix = tokens(query[:left])
        if prefix and prefix[0] in {'en', 'in', 'sobre'} and all(p in STOPWORDS for p in prefix):
            spans.append((0, right))
        else:
            scope = SCOPE_BEFORE.search(query[:left])
            if scope and (
                reason == 'name'
                or tokens(label) == tokens(name)
                or re.search(
                    r'\b(?:repo|repositorio|repository|proyecto|project)\b', scope[0], re.I
                )
            ):
                spans.append((scope.start(), right))
    for left, right in sorted(set(spans), reverse=True):
        query = query[:left] + query[right:]
    return query.strip(' ,:\uff1a\n')


def select_repository(query, repositories, default, *, repo=None):
    """Prefer explicit names/aliases; descriptions only resolve a leading scoped phrase."""
    if isinstance(repositories, dict) and repo is not None and repo not in repositories:
        raise RepositoryRoutingError(
            'unknown_repository', f'Repository not configured: {repo}', [repo]
        )
    if not isinstance(repositories, dict) or default not in repositories:
        raise ValueError(
            f'Repository not configured: {default}; set repo in the skill configuration'
        )
    catalog = {}
    for name, settings in repositories.items():
        if not tokens(name) or not isinstance(settings, dict):
            raise ValueError('Repository entries require a readable name and a settings object')
        aliases = settings.get('aliases', [])
        description = settings.get('description', '')
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not tokens(alias) for alias in aliases
        ):
            raise ValueError(f'Repository {name}: aliases must be a list of non-empty names')
        if not isinstance(description, str):
            raise ValueError(f'Repository {name}: description must be a string')
        catalog[name] = {
            'names': [(name, 'name'), *((alias, 'alias') for alias in aliases)],
            'description': description,
        }
    query, embedded = extract_repo_selector(query)
    if repo is not None and embedded is not None and repo != embedded:
        raise RepositoryRoutingError(
            'conflicting_repository',
            'CLI and embedded --repo selectors disagree.',
            [repo, embedded],
        )
    explicit = repo if repo is not None else embedded
    if explicit is not None and explicit not in repositories:
        raise RepositoryRoutingError(
            'unknown_repository', f'Repository not configured: {explicit}', [explicit]
        )
    query_tokens = tokens(query)
    positions = list(re.finditer(r'[^\W_]+', query))
    matches = []
    for name, entry in catalog.items():
        for label, reason in entry['names']:
            parts = tokens(label)
            for start in range(len(query_tokens) - len(parts) + 1):
                if query_tokens[start : start + len(parts)] == parts:
                    matches.append((start, start + len(parts), name, reason, label))
    # A longer name owns its contained short name (toolium-examples vs toolium).
    matches = [
        match
        for match in matches
        if not any(
            other[0] <= match[0]
            and other[1] >= match[1]
            and other[1] - other[0] > match[1] - match[0]
            for other in matches
        )
    ]
    candidates = {match[2] for match in matches}
    if explicit is not None and candidates - {explicit}:
        raise RepositoryRoutingError(
            'conflicting_repository',
            'Question and --repo name different repositories.',
            candidates | {explicit},
        )
    if len(candidates) > 1:
        raise RepositoryRoutingError(
            'ambiguous_repository',
            'Several repositories are mentioned; clarify the target.',
            candidates,
        )
    if matches:
        match = sorted(matches, key=lambda item: (item[0], item[3] != 'name'))[0]
        _start, _end, name, reason, label = match
        routed_query = remove_repository_scope(query, matches, positions)
        if not routed_query.strip('¿? .,:'):
            raise ValueError('A repository selector requires a nonempty question')
        return {
            'repository': name,
            'reason': 'explicit' if explicit is not None else reason,
            'matched': explicit if explicit is not None else label,
            'query': routed_query,
        }
    if explicit is not None:
        return {'repository': explicit, 'reason': 'explicit', 'matched': explicit, 'query': query}
    scoped = PREFIX.match(query)
    if scoped:
        selector = set(tokens(scoped['selector'])) - STOPWORDS
        scores = {}
        for name, entry in catalog.items():
            words = set(tokens(entry['description'])) - STOPWORDS
            common = selector & words
            if len(common) >= 2 and len(common) / max(len(selector), 1) >= 0.6:
                scores[name] = len(common) / len(selector)
        if scores:
            best = max(scores.values())
            candidates = {name for name, score in scores.items() if score == best}
            if len(candidates) != 1:
                raise RepositoryRoutingError(
                    'ambiguous_repository',
                    'Description matches several repositories; clarify the target.',
                    candidates,
                )
            name = next(iter(candidates))
            return {
                'repository': name,
                'reason': 'description',
                'matched': scoped['selector'],
                'query': scoped['query'],
            }
        if set(tokens(scoped['selector'])) & {
            'repository',
            'repositorio',
            'repo',
            'proyecto',
            'project',
        }:
            raise RepositoryRoutingError(
                'unknown_repository', 'The explicitly requested repository is not configured.'
            )
    return {'repository': default, 'reason': 'default', 'matched': None, 'query': query}
