# CodeTrace technical walkthrough

[Español](../es/code-rag-recorrido-tecnico.md)

CodeTrace first prepares a repository snapshot, then retrieves and selects evidence for a query. The [workflow diagram](codetrace-flow.md) shows how those stages connect. This guide maps them to implementation entry points.

## Prepare the snapshot

| Stage | Implementation | Result |
| --- | --- | --- |
| Plan repositories | [build_indexes.py](../../scripts/build_indexes.py) · `build_plan()`, `main()` | Selects repositories and their dependencies, validates paths, and schedules all indexes before linking. |
| Discover and parse | [core.py](../../src/codetrace/core.py) · `discover()`, `index_repository()`, `units_for()` | Selects files, reads sources, and extracts structural units with AST, Tree-sitter, or a format-specific parser. |
| Build chunks | [core.py](../../src/codetrace/core.py) · `build_chunks()`, `partition()`, `split_budget()` | Creates citable ranges using lexical token estimates and overlap. Incremental indexing can reuse compatible chunks for unchanged files. |
| Link repositories | [repo_links.py](../../src/codetrace/repo_links.py) and [evidence_graph.py](../../src/codetrace/evidence_graph.py) | Relates indexed sources and normalizes static relationships as graph nodes and edges. |
| Prepare vectors | [prepare_embeddings.py](../../src/codetrace/prepare_embeddings.py), [embedding_enrichment.py](../../src/codetrace/embedding_enrichment.py), and [embedding_index.py](../../src/codetrace/embedding_index.py) | Builds v1 vectors from base text and v2 vectors from graph-enriched text. Reuses embeddings for unchanged rendered inputs when compatible. |

Chunking uses a lexical token count. Embedding uses the embedding model's input limits, and answer context has a separate evidence budget. Generation uses the provider output limit `generation.max_tokens`.

| Artifact | Contents and consumers |
| --- | --- |
| `NAME.chunks.json` | Chunk text and citation ranges, lexical index, source snapshots, manifests, and diagnostics. Used by linking, retrieval, and inventory. |
| `NAME.relationships.json` | Relationships, provenance, and `evidence_graph`. Used by structural search, evidence expansion, and v2 enrichment. |
| `NAME.vectors-v1.json`, `NAME.vectors-v2.json` | Semantic vectors for the base and enriched representations. Loaded according to the configured profile. |
| Optional sessions and reports | Store paginated search state or results and can contain source excerpts. |

The standard artifact directory is `indexes/` beside the configuration. [Repository preparation](repository-preparation.md) covers operational checks. [pyproject.toml](../../pyproject.toml) declares PyYAML and python-dotenv as base dependencies and optional extras for Tree-sitter, sentence-transformers, Anthropic, and OpenAI.

## Route, retrieve, and select evidence

The [CLI](../../src/codetrace/__main__.py) runs `answer`. [agent_query.py](../../src/codetrace/agent_query.py) handles `query`, including readiness and pagination. The `code-trace` skill invokes `answer`, and `code-trace-inventory` invokes `query --mode evidence`. Launchers read their local connection and run the CodeTrace Python executable without a shell. `--resolve-only` returns the routing decision before opening indexes or loading models.

| Stage | Implementation | Behavior |
| --- | --- | --- |
| Route | [repository_routing.py](../../src/codetrace/repository_routing.py) · `select_repository()` | Resolves repository names, aliases, and scope clauses using deterministic rules and a fallback repository. |
| Check artifacts | [preparation.py](../../src/codetrace/preparation.py) · `inspect_preparation()`, `evaluate_readiness()` | For `query`, checks compatibility and evaluates freshness using metadata or hashes. `answer` reports source and Git state separately. |
| Plan and find candidates | [retrieval.py](../../src/codetrace/retrieval.py) and [search.py](../../src/codetrace/search.py) | Apply source scope and run the configured search. Lexical search uses normalized terms and variants, structural search uses the graph, and semantic search compares query embeddings with stored vectors. |
| Rank | [hybrid_search.py](../../src/codetrace/hybrid_search.py) · `hybrid_search()` | Merge candidates by chunk, preserve source signals, and rank according to the active profile. |
| Build context | [context_api.py](../../src/codetrace/context_api.py), [intent_context.py](../../src/codetrace/intent_context.py), and [evidence_context.py](../../src/codetrace/evidence_context.py) | Select citable excerpts under chunk, character, and token budgets. Deduplicate and add related evidence when permitted. Pagination disables expansion to keep pages disjoint. |

Retrieval ranks candidates. Context budgets determine which excerpts the answer can cite. A match can therefore appear in metadata without its source excerpt. Both stages limit coverage.

## Generate and deliver

[rag_pipeline.py](../../src/codetrace/rag_pipeline.py) orchestrates retrieval and context selection. In evidence mode, `render_query()` returns JSON for the consuming agent. With a generation provider, [answering.py](../../src/codetrace/answering.py) checks permissions and sensitive filenames, builds a [grounded prompt](../../src/codetrace/grounded_prompt.py), calls the selected adapter, and validates citations against the context.

[generation_factory.py](../../src/codetrace/generation_factory.py) selects Ollama, Anthropic, OpenAI, or Azure OpenAI. Ollama uses HTTP through urllib, Anthropic uses its SDK, and OpenAI and Azure share the OpenAI SDK's Chat Completions JSON mode. Credential and endpoint rules depend on the provider. [generation.py](../../src/codetrace/generation.py) checks claims, certainty, paths, and citation ranges. These checks establish whether references are valid within the supplied context. [answer_display.py](../../src/codetrace/answer_display.py) formats the answer and optional evidence, and the skill forwards its output verbatim.

For [static flows](static-code-flows.md), generation enables intent-aware analysis of candidate HTTP handlers or explicit starting symbols. Traversal follows statically resolved `calls` edges. Context selection keeps edges only when both endpoints survive its budgets. The prompt and presentation expose the resulting partial graph.

## Count within an explicit scope

The standalone [inventory command](cli-inventory.md) follows a separate path through [inventory.py](../../src/codetrace/inventory.py) and [python_inventory.py](../../src/codetrace/python_inventory.py). It selects a YAML/JSON list or Python file, parses the indexed snapshot, applies structural filters or matches an explicit decorator, and calculates the total before pagination. Ambiguous scope returns `needs_scope`.
