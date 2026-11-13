"""Validate JSON files passed by pre-commit."""

import json
import sys
from pathlib import Path


def main(paths: list[str]) -> int:
    status = 0
    for name in paths:
        try:
            json.loads(Path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            print(f"{name}: {error}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
