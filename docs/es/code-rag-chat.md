# Chat local de CodeTrace (0.9.20)

[English](../en/local-chat.md)

El chat permite consultar los repositorios desde el navegador sin instalar una skill. CodeTrace recupera las evidencias y llama al proveedor y al modelo configurados mediante el entorno o `.env`; la interfaz muestra su respuesta sin una segunda interpretación por otro modelo.

## Preparación y arranque

Usar el entorno de CodeTrace y la configuración local habitual. Si se parte de cero:

```bash
make setup
cp config.example.json config.json
```

Editar `config.json` para definir repositorios y recuperación. Para habilitar la generación, copiar `.env.example` a `.env` en el directorio de ejecución y definir `CODETRACE_GENERATION_PROVIDER`, `CODETRACE_GENERATION_MODEL` y las credenciales necesarias. Los valores exportados tienen prioridad sobre `.env`. Preparar los artefactos y verificar el proveedor:

```bash
make indexes
make doctor
make check-provider  # Para un proveedor remoto, añadir PROVIDER_ARGS=--allow-remote
make chat
```

En un entorno ya preparado, basta con `make chat`. No requiere Docker, Node ni dependencias web adicionales. Abre `http://127.0.0.1:8765` en el navegador. Detener con `Ctrl+C` en la terminal.

Para abrir la interfaz en inglés, añade `CHAT_LANG=en` a `.env` y reinicia el chat. El valor predeterminado es `es`. La opción solo controla los textos de la interfaz.

Para cambiar puerto, configuración o evitar la apertura automática:

```bash
make chat CONFIG=/ruta/a/config.json CHAT_ARGS="--port 8877 --no-browser"
.venv/bin/python -m codetrace chat --config config.json --port 0 --no-browser
```

El puerto `0` elige uno libre y muestra la dirección en la terminal. `--timeout 600` fija el tiempo máximo total por consulta en segundos, por defecto diez minutos; el tiempo del proveedor sigue siendo el de `CODETRACE_GENERATION_TIMEOUT_SECONDS` y puede agotarse antes. Se utiliza el mismo Python que inicia el servidor, por defecto `.venv/bin/python` con Make.

## Uso

1. Elegir un repositorio. Se preselecciona `default_repository` si existe; si no, el primero de la configuración.
2. Escribir una pregunta y pulsar **Consultar**.
3. Leer la respuesta y desplegar **Evidencias**, **Limitaciones** o **Estado del índice**.

El selector equivale a `--repo`: establece explícitamente el repositorio. No es necesario escribir el argumento dentro de la pregunta. Una mención a otro repositorio como parte de la pregunta se conserva como texto de búsqueda. Si ambos repositorios comparten un alias, la selección del chat lo resuelve. Un alcance explícito hacia otro repositorio, como «En otro-repo, …», genera una aclaración con los repositorios candidatos. El chat conserva la pregunta para que puedas elegir un repositorio compatible con el alcance escrito y volver a enviarla. Los límites de recuperación y contexto, la selección del modelo y las comprobaciones del índice se heredan de `codetrace answer`; el chat no amplía la cobertura ni garantiza recuentos exhaustivos.

La respuesta se muestra como texto conservando sus saltos de línea, sin ejecutar HTML ni interpretar Markdown. Las evidencias conservan el contenido recuperado, archivo, líneas, certeza y distinción entre fuente citada y contexto. Se señala cuando un fragmento está truncado. Si las fuentes han cambiado, el estado muestra la necesidad de actualización y la orden incremental sugerida; no reconstruye índices automáticamente.

La casilla **Permitir enviar contexto al proveedor remoto configurado** está marcada por defecto. Puedes desmarcarla antes de consultar. El chat pasa `--allow-remote` a `answer` cuando la casilla está marcada. La autorización también cubre Ollama cuando el endpoint está fuera del equipo.

Los errores de configuración, índices o proveedor se muestran en la conversación. Si el proceso no devuelve un error JSON legible, el chat ofrece un mensaje genérico sin exponer stderr. Para diagnosticar:

```bash
make doctor
make check-provider
```

## Historial y ejecución

CodeTrace guarda los últimos tres turnos completados por repositorio y conversación
en `indexes/.conversations/conversations.sqlite3`, dentro del directorio de
configuración. La base está ignorada por Git en el checkout. El modelo puede
usar esos turnos para interpretar referencias de seguimiento. Cada pregunta
consulta el índice y valida las citas contra las evidencias recuperadas en ese turno.

El chat guarda el ID en la pestaña para continuar tras recargar. **Nueva conversación**
limpia la vista y comienza una sesión nueva en la siguiente consulta. La sesión
anterior sigue disponible por su ID. El panel **ID de conversación** permite copiar
el ID o pegar uno existente. Usa la misma configuración al continuar desde otro acceso.

```bash
code-trace answer --config config.json --repo aicc-tests --session new '¿Qué steps crean agentes?'
code-trace query --mode answer --config config.json --repo aicc-tests --session ID '¿Dónde se implementa el primero?'
```

Reemplaza `ID` por el valor `session` de la primera respuesta. La terminal
interactiva también acepta `--session new` o `--session ID`. Las consultas
desde la CLI sin `--session` son independientes.

El servidor admite una consulta activa a la vez y devuelve un aviso si otra pestaña intenta consultar simultáneamente. No hay streaming ni cancelación desde el navegador. Cerrar la pestaña no cancela una consulta en curso; esta termina o agota su tiempo máximo. Con MLX, el chat reutiliza el proceso que mantiene el modelo cargado. Los índices se vuelven a leer en cada consulta. Si el proceso agota el tiempo máximo, el chat lo termina y la siguiente consulta inicia otro.

El servidor lee `config.json` al listar repositorios y ejecutar consultas. Tras cambiar la lista de repositorios, recargar la página. Los cambios en `.env` se aplican a la siguiente consulta. Para cambiar las variables exportadas que hereda el servidor, reiniciarlo.

## Acceso local

El servidor escucha exclusivamente en `127.0.0.1`, valida Host y Origin y requiere un token de sesión para las API. No expone rutas arbitrarias del sistema de archivos ni la configuración completa. Los recursos de la interfaz se incluyen en el paquete Python y no cargan servicios externos. Las preguntas y respuestas de una sesión se guardan en la base local y se omiten del log HTTP. El proveedor conserva su propia política de tratamiento de datos.

Está pensado para uso personal en el equipo local, sin autenticación de usuarios, publicación en red ni acceso multiusuario. La protección de sesión restringe peticiones desde otros orígenes del navegador; no a procesos del mismo usuario que puedan abrir la página local.

## Índice SQLite experimental

En esta rama, `make chat`, `search`, `answer` y `evaluate-rag` prefieren
automáticamente la instantánea `.sqlite3` del repositorio. Los índices antiguos
siguen funcionando desde JSON hasta que se genere su instantánea SQLite.
Para preparar una instantánea a partir de un índice existente:

```bash
PYTHONPATH=src .venv/bin/python -m codetrace prepare-sqlite indexes/aicc-tests.chunks.json
make chat
```

SQLite obtiene los candidatos léxicos y carga las evidencias por ID. El grafo sigue
leyéndose desde su JSON. Cuando se usa SQLite, las consultas combinan recuperación
léxica y estructural. Las métricas y las salidas JSON de `answer` y `evaluate-rag`
identifican el backend en `index_backend`.

Después de cambiar el código, el usuario puede regenerar explícitamente los índices:

```bash
make indexes REPOS="aicc-tests"
```

`make indexes` y `make indexes-incremental` generan ambas instantáneas de
fragmentos. Se requiere SQLite con FTS5 y tokenizador trigrama.

## Preguntas sobre flujos (0.9.21)

Se puede preguntar «¿Cuál es la primera función al llegar una petición?», concretar «Flujo de la petición POST /orders» o pedir «Flujo desde NOMBRE». Cuando se reconoce esta intención, `answer` prioriza entradas candidatas y sus llamadas estáticas. El panel **Flujo estático del código** muestra relaciones apoyadas por las evidencias incluidas; no una traza de ejecución. Ver [alcance, preparación y límites del análisis](code-rag-flujos.md).

## Identidad visual (0.9.22)

La cabecera combina el ícono de `assets/branding/codetrace-dark-logo.svg` con el
nombre CodeTrace en texto. El chat también usa el ícono en la pestaña del
navegador. La copia de `src/codetrace/web/` se distribuye con el paquete Python
y se sirve localmente. Si se actualiza el original, sincroniza esa copia.

## Nombre del proyecto (0.9.23)

El proyecto y el chat utilizan la marca **CodeTrace**, y el paquete se llama `code-trace`. El comando público es `code-trace` y el módulo es `codetrace`. El comando `codetrace` sigue disponible. Ver [instalación y compatibilidad](code-trace.md).

## MLX LM en Apple silicon

Instala el extra con `uv sync --no-editable --extra mlx` junto con los demás extras que uses. Define `CODETRACE_GENERATION_PROVIDER=mlx` y usa como `CODETRACE_GENERATION_MODEL` la ruta a un directorio local de MLX LM con su configuración, tokenizador y pesos. Usa un modelo de instrucciones capaz de devolver el JSON solicitado. Deja vacías las variables de endpoint y proxy. Valida el modelo con `codetrace check-provider`. El límite `CODETRACE_GENERATION_MAX_TOKENS` se aplica al texto generado. El tiempo máximo de la consulta web se aplica a MLX. El timeout del proveedor HTTP se usa con proveedores HTTP.

La primera consulta carga los pesos. Las siguientes reutilizan el modelo mientras el chat esté abierto y la configuración de generación sea la misma. Reinicia el chat si reemplazas los pesos en la misma ruta.

Para comparar con un proceso nuevo por consulta, detén el chat y ejecútalo con:

```bash
make chat CHAT_ARGS="--fresh-process"
```

Repite las mismas preguntas con el mismo modelo, repositorio y presupuesto de contexto.
En `indexes/reports/requests.jsonl`, compara `total_seconds` de
`chat_request_persistent` y `chat_request_subprocess` para medir la consulta desde
el servidor. Los eventos `chat` incluyen la lectura de índices, la preparación
de la recuperación y los tiempos de MLX. `mlx_model_load_seconds` aparece
cuando se cargan los pesos, y `mlx_inference_seconds` mide la generación.
