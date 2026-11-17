# CodeTrace

[Español](../es/code-trace.md)

The Python distribution and public command are named `code-trace`. The Python module and the compatible command are named `codetrace`.

## Installation and use

```bash
make setup
.venv/bin/code-trace --help
.venv/bin/python -m codetrace doctor --config config.json
.venv/bin/code-trace chat --config config.json
```

With dependencies already installed, `uv run --no-sync code-trace --help` also works from the checkout. See [repository preparation](repository-preparation.md), [local chat](local-chat.md), [static code flows](static-code-flows.md), and [skill installation](skill-installation.md).

## Compatibility

Existing imports, scripts, configurations, artifacts, and format identifiers continue to work with `codetrace`. The skills are named `code-trace` and `code-trace-inventory` and use `python -m codetrace`. New connection files use `code_trace_root`; existing `code_rag_root` connections remain supported. If you rename the checkout directory yourself, update absolute references in skill connections and virtual environments.
