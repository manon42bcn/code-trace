"""Safety checks before sending repository evidence to a provider."""

from __future__ import annotations

import os

SENSITIVE_NAMES = {'.env', '.env.local', 'id_rsa', 'credentials.json'}


def validate_generation_context(context: dict, *, allow_remote: bool = False) -> None:
    """Reject sensitive files or remote generation without explicit consent."""
    if not allow_remote:
        raise PermissionError('remote generation requires explicit allow_remote=True')
    for item in context.get('items', []):
        path = item.get('citation', {}).get('path') or ''
        if os.path.basename(path) in SENSITIVE_NAMES:
            raise PermissionError(f'sensitive path excluded from generation: {path}')
