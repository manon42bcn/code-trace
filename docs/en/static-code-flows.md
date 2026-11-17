# Querying static code flows

[Español](../es/code-rag-flujos.md)

`codetrace answer` and the local chat recognize questions about entry points and call flows. With generation enabled, the pipeline prioritizes structural candidates and supplies a bounded subgraph to the model.

```bash
.venv/bin/python -m codetrace answer --config config.json --repo demo \
  --output-format markdown --include-evidence "Show the flow from authenticate"
```

Try “What is the flow of POST /orders?” or “Show the flow from create_order”. Use indexed symbols and route literals. For methods use the indexed name, such as `Class.method`.

## Recognition and traversal

- Python HTTP detection recognizes decorators on objects explicitly constructed with FastAPI, APIRouter, Flask, or Blueprint. It resolves import aliases and up to four re-export hops. It accepts HTTP verb decorators, `route`, and `api_route` with positional literals or `path`/`rule`, and literal method lists or tuples.
- Method and path literals in the question restrict candidate handlers. Unspecified methods remain `UNSPECIFIED`. Router registration, mounting, prefixes, dynamic registration, and matching concrete URLs to parameterized routes are outside this analysis.
- Explicit starting symbols use exact matching. Without a recognizable starting point, retrieved Python symbols can become candidates. Traversal follows `calls` edges supported by `static_unique_call_target` within the queried index. Dynamic dispatch and unresolved instance methods can leave gaps.
- Traversal selects at most five entry candidates, forty nodes, and four call levels. It is deterministic and handles cycles. `traversal_truncated` records a traversal limit. Context selection also limits chunks, characters, and tokens, and retains only edges whose endpoints are both included.

## Reading the result

JSON context includes `code_flow` with candidate entries, edges, counts, and warnings. The chat panel and CLI output with `--include-evidence` display the static relationships. The prompt asks the model to cite each step and request a more specific route or symbol when necessary. Edges describe possible calls derived from indexed code. Server dispatch, middleware, callbacks, and framework dependencies can precede a candidate handler.

Evidence-only `query` retains its normal retrieval and pagination. The analysis uses the existing index and relationship graph without running repository code. If the artifacts are missing or stale, run `make indexes-incremental REPOS="NAME"`. See the [technical walkthrough](technical-walkthrough.md).
