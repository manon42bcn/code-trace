# Consultar flujos de código (0.9.21)

`coderag answer` y el chat local reconocen preguntas sobre flujos y puntos de entrada. Recuperan evidencias estructurales antes de los resultados de texto genéricos y proporcionan al modelo un conjunto acotado de relaciones entre funciones.

## Ejemplos

En el chat, seleccionar el repositorio y preguntar:

- «¿Cuál es la primera función al llegar una petición?»
- «¿Cuál es el flujo de la petición POST /orders?»
- «Muéstrame el flujo desde create_order».

También se puede usar la CLI:

```bash
.venv/bin/python -m codetrace answer \
  --config config.json --repo demo \
  --output-format markdown --include-evidence \
  "Muéstrame el flujo desde authenticate"
```

Los nombres y rutas son ejemplos; deben corresponder al código indexado. La selección de repositorio, el modelo, el proveedor y los límites siguen definidos por la configuración habitual.

## Qué se analiza

Para preguntas HTTP, se reconocen handlers Python con decoradores de objetos construidos explícitamente con `FastAPI`, `APIRouter`, `Flask` o `Blueprint`. Se resuelven aliases de importación y hasta cuatro saltos de reexportación de routers entre módulos indexados. Se admiten decoradores de métodos HTTP, `route` y `api_route`, con rutas literales posicionales o en `path`/`rule`, y listas/tuplas literales de `methods`.

Una ruta declarada no prueba que esté montada ni disponible en ejecución. No se resuelven prefijos ni registros `include_router`/`register_blueprint`; `/orders` significa el literal del decorador, no necesariamente la URL pública completa. Si `methods` no está explícito en `route`/`api_route`, se conserva `UNSPECIFIED` y se considera un candidato con método sin resolver. Una ruta literal o método explícitos en la pregunta restringen los candidatos reconocidos. No se hace matching de URLs concretas contra parámetros, por ejemplo `/orders/42` contra `/orders/{id}`.

Para un flujo desde una función se puede usar «flujo desde NOMBRE», «flow from NAME» o «flujo de NOMBRE». Se buscan símbolos Python exactos; para métodos, usar el nombre indexado como `Clase.metodo`. Si no se especifica un inicio reconocible, se consideran los símbolos Python recuperados, con su posible ambigüedad.

A partir de los candidatos se recorren las aristas `calls` con evidencia `static_unique_call_target` del grafo de relaciones existente. El recorrido permanece en chunks del índice consultado. Su soporte de resolución es el del grafo actual: llamadas a funciones con enlace estático único e imports explícitos; no se supone resolución de métodos de instancia ni despacho dinámico.

## Respuesta y panel del chat

El contexto JSON incluye `code_flow`, con entradas candidatas, llamadas entre fragmentos incluidos, conteos, límites y advertencias. El modelo recibe instrucciones para citar cada paso, reconocer huecos y pedir método/ruta o símbolo cuando haya varias entradas. Si no reconoce una entrada, debe indicar la insuficiencia del análisis; no afirmar que el repositorio carezca de ella.

El chat muestra un panel **Flujo estático del código**, con candidatos, archivos y líneas y relaciones `origen → destino`. La salida Markdown/texto con `--include-evidence` también incluye una sección de flujo. La respuesta literal del proveedor se conserva.

Las flechas representan posibles llamadas, **no una secuencia de ejecución ni una traza runtime**. La primera función del handler de la aplicación no equivale a la primera función del servidor: middleware, dependencias del framework, callbacks y dispatch previo quedan sin resolver.

## Límites y preparación

- Reconocimiento HTTP inicial para FastAPI/Flask en Python. Otros frameworks, lenguajes, constructores dentro de factories y registros dinámicos requieren ampliaciones.
- Máximo cinco funciones iniciales, cuarenta nodos y cuatro niveles de llamadas; ciclos controlados y recorrido determinista. `traversal_truncated` indica cortes por esos límites.
- Los límites de chunks, caracteres y tokens de contexto siguen aplicándose. Solo se muestran aristas cuyos dos extremos estén entre las evidencias efectivamente incluidas. Puede quedar un flujo incompleto aunque se hayan encontrado más llamadas.
- Una pregunta sin endpoint puede tener múltiples handlers. No se elige arbitrariamente uno como primero global.
- Este tratamiento se activa en respuestas con proveedor de generación. El modo de evidencias de `query` mantiene sus candidatos y paginación habituales.

No cambia el formato de los índices ni ejecuta código del repositorio para descubrir handlers. Con índices y relaciones actuales, no requiere reindexación por esta versión. Si faltan relaciones o el código ha cambiado, preparar nuevamente:

```bash
make indexes-incremental REPOS="NOMBRE"
```

El análisis usa la instantánea indexada y conserva los avisos de frescura que ya proporciona `answer`.
