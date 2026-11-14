<picture>
  <source media="(prefers-color-scheme: dark)" srcset="img/codetrace-logo.svg">
  <img src="img/codetrace-logo-light.svg" alt="CodeTrace — Understand the code. Follow the evidence." width="420">
</picture>

# code-trace

CodeTrace permite consultar repositorios de código con respuestas respaldadas por evidencias: archivos, líneas y fragmentos de la instantánea indexada. Puede utilizarse desde una CLI, un chat web local o skills instaladas en otro repositorio.

El proyecto está en desarrollo. El proveedor y el modelo de generación se eligen en la configuración local; pueden ser locales o remotos. La plantilla ilustra una configuración posible y no establece un modelo recomendado o definitivo para el proyecto.

## Qué incluye

- Indexación estructural de código, Gherkin, YAML, JSON y otros formatos configurados.
- Relaciones estáticas entre funciones y repositorios, con soporte específico para pasos Behave.
- Recuperación léxica, estructural y semántica opcional, con presupuestos de contexto explícitos.
- Respuestas con citas y evidencias, inventarios acotados a estructuras compatibles y búsquedas paginadas.
- Diagnóstico de preparación, proveedor y frescura de las fuentes indexadas, con referencia al commit Git.
- Chat local y análisis de flujos estáticos de código.

## Arranque local

Requisitos: Python 3.10 o posterior, `uv` y `make` para los comandos de esta guía. No se necesita Docker. El proveedor de generación elegido debe estar configurado y accesible para producir respuestas.

Desde el checkout:

```bash
make setup
cp config.example.json config.json
```

En una instalación existente, conservar el `config.json` propio. Este archivo está ignorado por Git; la plantilla versionada es [config.example.json](config.example.json).

Editar en `config.json`:

| Apartado | Qué configura |
| --- | --- |
| `repositories` | Nombres, rutas, aliases y descripciones de los repositorios consultables. |
| `relationships` | Dependencias y relaciones entre repositorios. |
| `indexing` | Lenguajes, exclusiones y generación de chunks. |
| `retrieval` | Recuperación y embeddings opcionales. |
| `context` | Límites de evidencias enviadas al modelo. |
| `generation` | Proveedor, modelo y parámetros de generación. |
| `skills.installations` | Destinos y repositorios de las skills instaladas. |

Después de ajustar la configuración:

```bash
make indexes
make doctor
make check-provider
make chat
```

`make indexes` genera chunks, relaciones y los vectores semánticos habilitados. La primera preparación puede requerir descargar el modelo de embeddings configurado. `make doctor` diagnostica la preparación y `make check-provider` comprueba el proveedor generativo. Si se elige Anthropic, instalar también el extra `llm`, conservando los extras de preparación:

```bash
uv sync --extra parsers --extra embeddings --extra llm --group dev
```

Configurar sus credenciales mediante `ANTHROPIC_API_KEY` o `ANTHROPIC_AUTH_TOKEN` en el entorno del proceso.

El chat se abre en `http://127.0.0.1:8765`. Seleccionar un repositorio, escribir una pregunta y desplegar las evidencias o el estado del índice. Detener el servidor con `Ctrl+C`.

Más detalles en [preparación de repositorios](docs/code-rag-preparacion.md) y [chat local](docs/code-rag-chat.md).

## CLI

Tras `make setup`, se puede utilizar el comando instalado o el módulo Python:

```bash
.venv/bin/code-trace --help
.venv/bin/python -m codetrace --help
```

Ejemplos con el repositorio `demo` de la plantilla:

```bash
# Respuesta del proveedor configurado, con evidencias.
.venv/bin/code-trace answer "¿Dónde se valida la autenticación?" \
  --config config.json --repo demo --output-format markdown --include-evidence

# Evidencias estructuradas, sin generar una respuesta con el proveedor de CodeTrace.
.venv/bin/code-trace query "autenticación" --config config.json --repo demo --mode evidence

# Diagnóstico de la preparación.
.venv/bin/code-trace doctor --config config.json --repo demo
```

Para autorizar el envío de evidencias al proveedor remoto configurado, añadir `--allow-remote` a la consulta; el chat ofrece la casilla equivalente.

El módulo `coderag` sigue disponible por compatibilidad. Los comandos públicos actuales son `code-trace` y `python -m codetrace`.

## Comandos de mantenimiento

| Comando | Uso |
| --- | --- |
| `make indexes` | Preparar todos los repositorios configurados. |
| `make indexes REPOS="demo"` | Preparar una selección y sus dependencias. |
| `make indexes-plan` | Revisar el plan sin generar artefactos. |
| `make indexes-incremental REPOS="demo"` | Actualizar artefactos reutilizando archivos sin cambios. |
| `make doctor` | Diagnosticar preparación y estado de las fuentes. |
| `make check-provider` | Verificar el proveedor de generación. |
| `make chat` | Arrancar la interfaz local. |
| `make evaluate-real` | Evaluar la recuperación con la batería de preguntas reales. |

Se puede seleccionar otra configuración con `CONFIG=/ruta/config.json`. Los artefactos generados en `indexes/` están ignorados por Git y se regeneran a partir de los repositorios configurados.

## Skills

| Skill | Comportamiento |
| --- | --- |
| `code-trace` | Invoca `codetrace answer` y devuelve literalmente la respuesta del modelo configurado en CodeTrace, con sus evidencias. |
| `code-trace-inventory` | Invoca `codetrace query --mode evidence`; el modelo que ejecuta la skill interpreta las evidencias. |

Declarar los destinos en `skills.installations` de `config.json` y ejecutar:

```bash
make skills-install SKILL_ARGS="--dry-run"
make skills-install
make skills-status
make skills-update
```

Las conexiones usan `code_trace_root` y `repo`. Los lanzadores utilizan el Python del entorno de CodeTrace y heredan su catálogo y configuración. No reconstruyen índices automáticamente al consultar. El registro local de instalaciones es `skills/installations.local.json`.

Ver [instalación de skills](docs/skills-instalacion.md), [skill code-trace](docs/skill-code-rag.md) y [skill code-trace-inventory](docs/skill-code-inventory.md).

## Alcance de las respuestas

La recuperación tiene límites de candidatos, chunks, caracteres y tokens. Las evidencias recuperadas no equivalen a un análisis exhaustivo del repositorio ni garantizan un recuento global. Los inventarios completos requieren un alcance explícito compatible: ver [inventarios](docs/code-rag-inventory.md).

El análisis de flujo sigue llamadas estáticas entre símbolos Python e identifica candidatos HTTP de FastAPI/Flask. No es una traza de ejecución; middleware, montaje de routers y despacho dinámico pueden quedar sin resolver. Ver [flujos de código](docs/code-rag-flujos.md).

El historial del chat solo permanece en la pestaña. Cada pregunta es independiente y no recibe automáticamente la conversación anterior. Las consultas utilizan la instantánea indexada; los avisos de frescura no reconstruyen los índices por sí solos.

## Desarrollo y documentación

```bash
make lint
make format-check
.venv/bin/python -m pytest -q
make hooks-install
```

Ruff configura lint y formato en [pyproject.toml](pyproject.toml). El lint JSON y los hooks están definidos en el repositorio. Algunas pruebas levantan servidores HTTP temporales en localhost.

- [Guía del proyecto y compatibilidad](docs/code-trace.md).
- [Recorrido técnico](docs/code-rag-recorrido-tecnico.md).
- [Historial de cambios](CHANGELOG.md).

Con cada versión se actualizan `pyproject.toml`, la documentación afectada y `CHANGELOG.md`, y se registra el cambio mediante un commit descriptivo.
