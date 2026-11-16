"""Explicit evidence-only budget profiles, independent of generation settings."""

import copy

DEFAULTS = {'limit': 10, 'max_chunks': 5, 'max_chars': 12000}
KEYS = {*DEFAULTS, 'max_tokens'}


def apply_budget_profile(raw, name):
    defaults = dict(DEFAULTS)
    if name is None:
        return raw, defaults
    profiles = raw.get('query_profiles', {})
    if not isinstance(profiles, dict):
        raise ValueError('query_profiles must be an object')
    profile = profiles.get(name, {})
    if not isinstance(profile, dict) or set(profile) - KEYS:
        raise ValueError('Query budget profiles support only limit/max_chunks/max_chars/max_tokens')
    for key, value in profile.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f'Query budget {key} must be a positive integer')
    raw = copy.deepcopy(raw)
    if 'limit' in profile:
        raw['retrieval'] = {**(raw.get('retrieval') or {}), 'limit': profile['limit']}
        for repository in raw.get('repositories', {}).values():
            repository['retrieval'] = {
                **(repository.get('retrieval') or {}),
                'limit': profile['limit'],
            }
    raw['context'] = {
        **(raw.get('context') or {}),
        **{k: v for k, v in profile.items() if k != 'limit'},
    }
    defaults.update({k: v for k, v in profile.items() if k in defaults})
    return raw, defaults


def resolve_cli_budgets(args, defaults):
    for key, value in defaults.items():
        if getattr(args, key) is None:
            setattr(args, key, value)
