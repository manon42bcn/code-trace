# Flujo de CodeTrace

[English](../en/codetrace-flow.md)

El diagrama sigue la preparación de un repositorio y el recorrido de una pregunta por `codetrace answer`. El modo interactivo y el chat web delegan en ese comando.

```mermaid
flowchart TD
    subgraph prep["Preparación del repositorio"]
        config["Repositorio y configuración"]
        config --> index["codetrace index<br/>Descubrir archivos y crear fragmentos con líneas de origen"]
        index --> chunks["Índice JSON de fragmentos"]
        config --> link["codetrace link"]
        chunks --> link
        link --> graph["JSON de relaciones con grafo de evidencias"]
        chunks --> embed["codetrace embed<br/>Preparación semántica opcional"]
        graph --> embed
        embed --> vectors["Almacenes de vectores"]
    end

    subgraph query["De la pregunta a la respuesta"]
        entry["Pregunta desde la CLI, el modo interactivo o el chat web"]
        entry --> load["codetrace answer<br/>Resolver rutas, cargar artefactos y comprobar el estado del índice"]
        load --> retrieve["Recuperar candidatos<br/>Búsqueda léxica, estructural y semántica según configuración"]
        retrieve --> context["Seleccionar evidencias según la intención y los límites de contexto"]
        context --> enabled{"¿Hay un proveedor de generación configurado?"}
        enabled -->|No| prompt["Construir el prompt y devolver contexto y prompt en JSON"]
        enabled -->|Sí| permission["Comprobar permisos de generación y nombres de archivo sensibles"]
        permission --> grounded["Construir el prompt con fragmentos y rangos citables"]
        grounded --> llm["Generar con Ollama, Anthropic, OpenAI, Azure OpenAI, OpenRouter o Groq"]
        llm --> validate["Validar la respuesta estructurada contra el contexto"]
        validate --> output["Mostrar la respuesta en JSON, texto o Markdown"]
    end

    chunks --> load
    graph --> load
    vectors -.-> load
```

- La [preparación](code-rag-preparacion.md) se ejecuta aparte de la consulta. Los vectores se cargan según el perfil de recuperación configurado.
- La generación remota requiere autorización explícita con `--allow-remote` en la CLI. El flujo muestra las salidas exitosas. Los fallos de configuración, permisos o validación interrumpen la consulta.
- Para seguir la implementación, entra por el [CLI](../../src/codetrace/__main__.py), continúa en el [pipeline RAG](../../src/codetrace/rag_pipeline.py) y termina en la [generación y validación](../../src/codetrace/answering.py).
