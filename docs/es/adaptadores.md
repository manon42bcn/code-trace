# Adaptadores de CodeTrace

CodeTrace tiene dos contratos. `GenerationProvider` recibe un prompt y devuelve
un `GenerationResult`. `EmbeddingProvider` expone `metadata`,
`embed_documents` y `embed_query`. Las clases pueden implementar el contrato
directamente mediante tipado estructural.

| Tipo | Clases y registro | Selección en `.env` |
| --- | --- | --- |
| Generación | `src/codetrace/providers/llm/` | `CODETRACE_GENERATION_PROVIDER` y `CODETRACE_GENERATION_MODEL` |
| Embeddings | `src/codetrace/providers/embeddings/` | `CODETRACE_EMBEDDING_PROVIDER` y `CODETRACE_EMBEDDING_MODEL` |

## Añadir un adaptador

1. Implementa la clase en el directorio correspondiente. Mantén la traducción
   de peticiones y respuestas dentro del adaptador. Importa las dependencias
   opcionales al crear o usar el adaptador.
2. Añade una entrada al `registry.py` de ese tipo. En generación, registra la
   función constructora, indica si requiere un modelo explícito y declara si
   contacta un servicio remoto, usa loopback o ejecuta localmente. La política de
   consentimiento de CodeTrace utiliza esa declaración.
3. En embeddings, registra la función constructora, la comprobación de
   dependencias para `doctor` y la resolución del nombre o ruta del modelo.
   Da al adaptador un prefijo de identificador y un sufijo de archivo propios.
   El constructor recibe el identificador resultante. Mantenlo estable para que
   los vectores preparados sigan siendo compatibles cuando corresponda.
4. Añade una prueba que seleccione el adaptador desde la configuración y ejerza
   su contrato con un SDK, modelo o servicio simulado.

Las llamadas de generación comparten la medición de latencia. El adaptador
puede publicar tiempos propios en `last_timings`, como la carga y la
inferencia de MLX. Las consultas e indexaciones semánticas se registran como
`embedding_query` y `embedding_index` en `indexes/reports/requests.jsonl`.
El historial contiene identificadores de adaptador y modelo, estado y tiempos.
