"""One-file subprocess boundary for parser crashes / hangs."""

import json
import sys

from .core import build_chunks


def main():
    request = json.load(sys.stdin)
    diagnostics = []
    try:
        rows = build_chunks(
            request['path'], request['language'], request['source'], request['config'], diagnostics
        )
        json.dump({'chunks': rows, 'diagnostics': diagnostics}, sys.stdout, ensure_ascii=False)
    except Exception as exc:
        json.dump({'error': f'{type(exc).__name__}: {exc}'}, sys.stdout, ensure_ascii=False)
        sys.exit(2)


if __name__ == '__main__':
    main()
