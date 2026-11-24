# Adaptadores de CodeTrace

[English](../en/adapters.md)

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

## Ejemplo de generación

Guarda este adaptador de prueba como
`src/codetrace/providers/llm/example.py`. Devuelve una respuesta fija para
probar la integración local. En un adaptador real, `generate` llama al SDK,
traduce la salida a `GenerationResult` y conserva los identificadores de
evidencia que devuelve el proveedor. La validación de citas se ejecuta en el
pipeline.

```python
from ...generation import GenerationResult
from ...generation_config import GenerationConfig


class ExampleGenerationProvider:
    provider = 'example'

    def __init__(self, config: GenerationConfig):
        self.model = config.model

    def generate(self, prompt: str, *, metadata: dict | None = None) -> GenerationResult:
        return GenerationResult(
            answer='Respuesta fija para probar el adaptador.',
            provider=self.provider,
            model=self.model,
        )
```

En `providers/llm/registry.py`, importa la clase con
`from .example import ExampleGenerationProvider` y añade esta entrada a
`GENERATION_PROVIDERS`:

```python
'example': GenerationRegistration(
    create=ExampleGenerationProvider,
    requires_model=True,
    execution='local',
),
```

Configura y verifica el ejemplo:

```dotenv
CODETRACE_GENERATION_PROVIDER=example
CODETRACE_GENERATION_MODEL=fixture-v1
```

```bash
make check-provider
```

Usa `execution='remote'` para un servicio externo y `execution='loopback'`
para un adaptador que expone `base_url` y puede conectar a una dirección local
o remota. Para probar un servicio remoto, usa
`make check-provider PROVIDER_ARGS="--allow-remote"`. Si el constructor
necesita credenciales o un endpoint, puedes registrar una función que lea esas
opciones y devuelva la clase configurada.

## Ejemplo de embeddings

Guarda este adaptador de prueba como
`src/codetrace/providers/embeddings/example.py`. Los dos valores que calcula
sirven para probar el contrato. Para recuperación real, sustituye el cálculo
por la llamada al modelo y conserva el orden de los vectores respecto a los
textos de entrada.

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

En `providers/embeddings/registry.py`, importa los tres nombres de
`.example` y añade esta entrada a `EMBEDDING_PROVIDERS`:

```python
'example': EmbeddingRegistration(
    create=ExampleEmbeddingProvider,
    check_runtime=check_example_runtime,
    resolve_model=resolve_example_model,
    model_prefix='example:',
    store_suffix='.example',
),
```

El registro añade el prefijo al modelo que devuelve el resolutor. Con los
valores siguientes, el constructor recibe `example:fixture-v1` y CodeTrace
genera archivos `*.vectors-v*.example.json`. En un adaptador real,
`check_runtime` debe devolver un mensaje accionable si falta una dependencia
o un archivo. Se puede comprobar la disponibilidad desde `doctor` sin cargar
los pesos.

```dotenv
CODETRACE_EMBEDDING_PROVIDER=example
CODETRACE_EMBEDDING_MODEL=fixture-v1
```

Con los fragmentos y relaciones ya preparados, ejecuta:

```bash
PYTHONPATH=src .venv/bin/python -m codetrace embed --config config.json --repo demo
make doctor REPOS=demo
```

Usa el mismo identificador, dimensiones y configuración para preparar los
vectores y consultar. Si cambia el modelo, el preprocesamiento o las
dimensiones, cambia el identificador o `config_version` según corresponda y
regenera los vectores. Conserva el formato del identificador para las
configuraciones compatibles.

## Configuración y pruebas

[.env.example](../../.env.example) enumera los adaptadores incluidos y sus
variables. Copia a `.env` solo los bloques que uses. Las variables exportadas
en la terminal tienen prioridad sobre el archivo.

Al añadir una implementación, prueba que se seleccione desde `.env`, que el
constructor traduzca sus opciones y que la salida cumpla el contrato. Para
embeddings, incluye una comprobación de dimensiones y de compatibilidad del
índice. Para generación remota, cubre el consentimiento. Los ejemplos
automatizados de registro están en
[`tests/test_provider_registries.py`](../../tests/test_provider_registries.py).
