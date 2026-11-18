# Installing CodeTrace skills

[Español](../es/skills-instalacion.md)

Declare installations in `skills.installations` in CodeTrace's `config.json`.

```json
{
  "skills": {
    "installations": [
      {
        "destination": "../demo/.claude/skills",
        "repo": "demo",
        "names": ["code-trace", "code-trace-inventory"]
      }
    ]
  }
}
```

The destination is a parent directory and resolves relative to `config.json`. The installer stores its local registry in `skills/installations.local.json`.

```bash
make skills-install SKILL_ARGS="--dry-run"
make skills-install
make skills-status
make skills-update
```

An explicit `--dest` selects one-off installation. `--skill code-trace` or `--skill code-trace-inventory` selects a single skill. Removing a declaration leaves the installed copy in place.

Managed copies include `config.example.json`. Local edits to managed files require review before an update. Each consumer checkout can create a gitignored `config.local.json` from the example and set its checkout path and default repository. Updates preserve the local connection settings. Use `code_trace_root` and `repo`. When both `code_trace_root` and the compatible `code_rag_root` field are present, they must resolve to the same checkout.

Invoke `/code-trace` for the configured provider's answer or `/code-trace-inventory` for evidence interpreted by the agent. Both launchers use the Python environment in the CodeTrace checkout. The evidence launcher prefers `query_profiles.code-trace-inventory` and falls back to `query_profiles.code-inventory`. Reload the agent window if its list of skills still shows the old names.
