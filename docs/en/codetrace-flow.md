# CodeTrace workflow

[Español](../es/flujo-codetrace.md)

The diagram follows repository preparation and traces a question through `codetrace answer`. The interactive terminal and web chat delegate to that command.

```mermaid
flowchart TD
    subgraph prep["Repository preparation"]
        config["Repository and configuration"]
        config --> index["codetrace index<br/>Discover files and create chunks with source line numbers"]
        index --> chunks["JSON chunk index"]
        config --> link["codetrace link"]
        chunks --> link
        link --> graph["Relationships JSON with evidence graph"]
        chunks --> embed["codetrace embed<br/>Optional semantic preparation"]
        graph --> embed
        embed --> vectors["Vector stores"]
    end

    subgraph query["From question to answer"]
        entry["Question from the CLI, interactive terminal, or web chat"]
        entry --> load["codetrace answer<br/>Resolve paths, load artifacts, and check index status"]
        load --> retrieve["Retrieve candidates<br/>Lexical, structural, and semantic search as configured"]
        retrieve --> context["Select evidence based on intent and context limits"]
        context --> enabled{"Is a generation provider configured?"}
        enabled -->|No| prompt["Build the prompt and return context and prompt as JSON"]
        enabled -->|Yes| permission["Check generation permissions and sensitive filenames"]
        permission --> grounded["Build the prompt with excerpts and citable line ranges"]
        grounded --> llm["Generate with Ollama, Anthropic, OpenAI, Azure OpenAI, OpenRouter, or Groq"]
        llm --> validate["Validate the structured answer against the context"]
        validate --> output["Display the answer as JSON, text, or Markdown"]
    end

    chunks --> load
    graph --> load
    vectors -.-> load
```

- [Preparation](repository-preparation.md) runs separately from queries. Vector loading depends on the configured retrieval profile.
- Remote generation requires explicit authorization through `--allow-remote` in the CLI. The diagram shows successful paths. Configuration, permission, or validation failures stop the query.
- To follow the implementation, start with the [CLI](../../src/codetrace/__main__.py), continue through the [RAG pipeline](../../src/codetrace/rag_pipeline.py), and finish with [generation and validation](../../src/codetrace/answering.py).
