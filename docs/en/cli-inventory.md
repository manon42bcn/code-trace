# CodeTrace inventories

[Español](../es/code-rag-inventory.md)

The standalone `codetrace inventory` command counts entries in indexed snapshots. It runs without a generation provider. The `code-trace` skill uses `answer`, and the `code-trace-inventory` skill uses evidence retrieval.

## Count entries in a YAML or JSON list

```bash
.venv/bin/python -m codetrace inventory --config config.json --repo demo \
  --file accounts.json \
  --path '$/accounts' --unique-by username
```

The total covers the entire selected scope before pagination. Use `--where FIELD=VALUE` for exact scalar filters, `--group-by FIELD` for grouping, and `--unique-by FIELD` to group occurrences by identity. With `--default-repo`, question text can route to a repository. List selection requires structural scope. Ambiguity produces `needs_scope` with candidate lists.

## Count functions with an explicit Python decorator

```bash
.venv/bin/python -m codetrace inventory --config config.json --repo demo_library \
  --kind python-decorators --file features/steps/common.py \
  --decorator given
```

AST analysis includes nested and async functions and counts each matching function once. It leaves aliases, dynamic expressions, and conditional registration unresolved. It uses the indexed source snapshot without importing repository code. Prepare the repository again if the required snapshot is missing.
