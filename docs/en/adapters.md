# CodeTrace adapters

[Español](../es/adaptadores.md)

CodeTrace has two provider contracts. `GenerationProvider` takes a prompt
and returns a `GenerationResult`. `EmbeddingProvider` exposes `metadata`,
`embed_documents`, and `embed_query`. Classes implement these contracts
through structural typing.

| Type | Implementations and registry | Selection in `.env` |
| --- | --- | --- |
| Generation | [`providers/llm/`](../../src/codetrace/providers/llm/) | `CODETRACE_GENERATION_PROVIDER` and `CODETRACE_GENERATION_MODEL` |
| Embeddings | [`providers/embeddings/`](../../src/codetrace/providers/embeddings/) | `CODETRACE_EMBEDDING_PROVIDER` and `CODETRACE_EMBEDDING_MODEL` |

## Add an adapter

1. Put the class in the corresponding directory. Translate requests and
   responses inside the adapter. Import optional dependencies when the
   adapter is created or used.
2. Add an entry to that directory's `registry.py`. For generation, register
   the constructor, specify whether a model must be configured explicitly,
   and declare the execution type. CodeTrace uses that type to enforce
   consent for remote calls.
3. For embeddings, register the constructor, a runtime check for `doctor`,
   and a model name or path resolver. Give the adapter its own model ID
   prefix and vector filename suffix. Keep the resulting model ID stable
   for compatible vector indexes.
4. Add a test that selects the adapter from configuration and exercises
   its contract with a simulated SDK, model, or service.

Generation calls share latency measurement. An adapter can report its own
timings in `last_timings`, such as MLX model loading and inference. Semantic
queries and vector indexing appear as `embedding_query` and
`embedding_index` in `indexes/reports/requests.jsonl`. The log records
adapter and model IDs, status, and timings.

## Generation example

Save this test adapter as `src/codetrace/providers/llm/example.py`. It returns
a fixed response for testing the local integration. A real `generate`
implementation calls the SDK, converts its output to `GenerationResult`,
and preserves the evidence identifiers returned by the provider. The
pipeline validates citations.

```python
from ...generation import GenerationResult
from ...generation_config import GenerationConfig


class ExampleGenerationProvider:
    provider = 'example'

    def __init__(self, config: GenerationConfig):
        self.model = config.model

    def generate(self, prompt: str, *, metadata: dict | None = None) -> GenerationResult:
        return GenerationResult(
            answer='Fixed response for testing the adapter.',
            provider=self.provider,
            model=self.model,
        )
```

In `providers/llm/registry.py`, import the class with
`from .example import ExampleGenerationProvider` and add this entry to
`GENERATION_PROVIDERS`:

```python
'example': GenerationRegistration(
    create=ExampleGenerationProvider,
    requires_model=True,
    execution='local',
),
```

Select it in `.env`:

```dotenv
CODETRACE_GENERATION_PROVIDER=example
CODETRACE_GENERATION_MODEL=fixture-v1
```

Run the generation probe:

```bash
make check-provider
```

Use `execution='remote'` for an external service and `execution='loopback'`
for an adapter that exposes `base_url` and can connect to a local or remote
address. To probe a remote service, run
`make check-provider PROVIDER_ARGS="--allow-remote"`. If the constructor
needs credentials or an endpoint, register a function that reads those
settings and returns the configured adapter.

## Embedding example

Save this test adapter as `src/codetrace/providers/embeddings/example.py`.
It returns two values to exercise the contract. For semantic retrieval,
use the chosen embedding model and return vectors in the same order as
the input texts.

```python
from collections.abc import Sequence

from ...embeddings import EmbeddingMetadata, validate_vectors


class ExampleEmbeddingProvider:
    def __init__(self, model_id: str):
        self.metadata = EmbeddingMetadata(
            model_id=model_id,
            dimensions=2,
            config_version='v1',
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = [[1.0, float(len(text))] for text in texts]
        validate_vectors(vectors, self.metadata)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def resolve_example_model(configured: str, model: str | None) -> str:
    return model or configured


def check_example_runtime(model_id: str) -> str | None:
    return None
```

In `providers/embeddings/registry.py`, import the three names from
`.example` and add this entry to `EMBEDDING_PROVIDERS`:

```python
'example': EmbeddingRegistration(
    create=ExampleEmbeddingProvider,
    check_runtime=check_example_runtime,
    resolve_model=resolve_example_model,
    model_prefix='example:',
    store_suffix='.example',
),
```

The registry adds the prefix to the model identifier returned by
`resolve_model`. With the settings below, the constructor receives
`example:fixture-v1` and CodeTrace writes `*.vectors-v*.example.json` files.
A real `check_runtime` should return a message that explains how to fix a
missing dependency or file. This lets `doctor` check availability without
loading model weights.

```dotenv
CODETRACE_EMBEDDING_PROVIDER=example
CODETRACE_EMBEDDING_MODEL=fixture-v1
```

Once the chunks and relationships are prepared, run:

```bash
PYTHONPATH=src .venv/bin/python -m codetrace embed --config config.json --repo demo
make doctor REPOS=demo
```

Use the same model identifier, dimensions, and configuration for indexing
and querying. If the model, preprocessing, or dimensions change, update
the model ID or `config_version` as appropriate and rebuild the vectors.
Keep the identifier format stable across compatible configurations.

## Configuration and tests

[.env.example](../../.env.example) lists the built-in adapters and their
settings. Copy the relevant blocks into `.env`. Exported environment
variables take precedence over the file.

Test that configuration selects the adapter, the constructor translates its
options, and the output follows the contract. For embeddings, check vector
dimensions and index compatibility. For remote generation, test consent
handling. See the [registry tests](../../tests/test_provider_registries.py)
for working examples.
