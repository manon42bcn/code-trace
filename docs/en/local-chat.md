# CodeTrace local chat

[Español](../es/code-rag-chat.md)

The browser interface delegates each question to `codetrace answer`. It displays the configured provider's answer, evidence, limitations, and index status.

## Setup and startup

From the checkout, run `make setup` and copy `config.example.json` to `config.json` if you do not have a local configuration. Set repositories and retrieval options in `config.json`. To enable generation, copy `.env.example` to `.env` in your working directory and set `CODETRACE_GENERATION_PROVIDER`, `CODETRACE_GENERATION_MODEL`, and any required credentials. Exported variables override `.env`. Then run:

```bash
make indexes
make doctor
make check-provider
make chat
```

For a remote provider, use `make check-provider PROVIDER_ARGS=--allow-remote`. On a prepared checkout, `make chat` opens `http://127.0.0.1:8765`. Stop it with Ctrl+C. The Python package includes the web assets.

```bash
make chat CONFIG=/path/to/config.json CHAT_ARGS="--port 8877 --no-browser"
.venv/bin/python -m codetrace chat --config config.json --port 0 --no-browser
```

Port zero selects a free port and prints the URL. The server starts each query with its own Python executable. `--timeout` controls the overall query deadline in seconds and defaults to 600. The provider's `CODETRACE_GENERATION_TIMEOUT_SECONDS` can expire sooner.

## Asking questions

Select a repository and submit a question. The default is `default_repository`, or the first configured repository if no default is set. The selection is equivalent to `--repo`. For a remote backend, enable the checkbox that allows sending evidence to the configured provider. The server passes `--allow-remote` to the CLI.

The answer is rendered as plain text. Evidence shows files, line ranges, certainty, and whether each excerpt was cited or supplied as context. The index panel reports source changes and suggests an incremental rebuild when appropriate. For static flow questions, the flow panel lists candidate entry points and relationships with supporting source lines. See [static code flows](static-code-flows.md).

Each question starts a new CLI process and has no conversational memory. The tab keeps visible history in memory until you reload, close it, or start a new conversation. The server handles one active query at a time. Closing the tab leaves a pending query running until it finishes or times out. Reload after changing the repository list. Changes to `.env` apply to the next query. Restart the server to update the exported variables it inherits.

## Local access

The server binds to `127.0.0.1`, checks Host and Origin, and requires a session token for API requests. It serves web assets locally. It keeps no persistent chat history and excludes question and answer text from the HTTP log. Provider data handling depends on the configured service. This interface is designed for personal local use. See [repository preparation](repository-preparation.md) for diagnosing artifact issues.

## MLX LM on Apple silicon

Install the extra with `uv sync --extra mlx` alongside any other extras you use. Set `CODETRACE_GENERATION_PROVIDER=mlx` and point `CODETRACE_GENERATION_MODEL` to a local MLX LM directory containing its configuration, tokenizer, and weights. Use an instruction model that can return the requested JSON. Leave endpoint and proxy settings empty. Validate the model with `codetrace check-provider`. `CODETRACE_GENERATION_MAX_TOKENS` limits the generated output. MLX runs inside the query process and the web chat’s overall query deadline still applies. The HTTP provider timeout does not apply to MLX.
