"""Safety checks before sending repository evidence to a provider."""

from __future__ import annotations

import os
from ipaddress import ip_address
from urllib.parse import urlsplit

from .providers.llm.registry import GENERATION_PROVIDERS

SENSITIVE_NAMES = {'.env', '.env.local', 'id_rsa', 'credentials.json'}


def is_local_generation_provider(provider) -> bool:
    entry = GENERATION_PROVIDERS.get(getattr(provider, 'provider', None))
    if entry is None:
        return False
    if entry.execution != 'loopback':
        return entry.execution == 'local'
    host = urlsplit(getattr(provider, 'base_url', 'http://localhost')).hostname
    if host == 'localhost':
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def validate_generation_context(context: dict, *, allow_remote: bool = False) -> None:
    """Reject sensitive files or remote generation without explicit consent."""
    if not allow_remote:
        raise PermissionError('remote generation requires explicit allow_remote=True')
    for item in context.get('items', []):
        path = item.get('citation', {}).get('path') or ''
        if os.path.basename(path) in SENSITIVE_NAMES:
            raise PermissionError(f'sensitive path excluded from generation: {path}')
