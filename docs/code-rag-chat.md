# Chat local de CodeTrace (0.9.20)

El chat permite consultar los repositorios desde el navegador sin instalar una skill. CodeTrace recupera las evidencias y llama al proveedor y al modelo definidos en `config.json`; la interfaz muestra su respuesta sin una segunda interpretación por otro modelo.

## Preparación y arranque

Usar el entorno de CodeTrace y la configuración local habitual. Si se parte de cero:

```bash
make setup
cp config.example.json config.json
```

Editar `config.json` para definir repositorios, recuperación y generación. La plantilla es un ejemplo; elegir el proveedor y el modelo que se quieran probar. Preparar los artefactos y verificar el proveedor:

```bash
make indexes
make doctor
make check-provider
make chat
```

En un entorno ya preparado, basta con `make chat`. No requiere Docker, Node ni dependencias web adicionales. Abre `http://127.0.0.1:8765` en el navegador. Detener con `Ctrl+C` en la terminal.

Para cambiar puerto, configuración o evitar la apertura automática:

```bash
make chat CONFIG=/ruta/a/config.json CHAT_ARGS="--port 8877 --no-browser"
.venv/bin/python -m codetrace chat --config config.json --port 0 --no-browser
```

El puerto `0` elige uno libre y muestra la dirección en la terminal. `--timeout 600` fija el tiempo máximo total por consulta en segundos, por defecto diez minutos; el tiempo del proveedor sigue siendo el de `generation.timeout_seconds` y puede agotarse antes. Se utiliza el mismo Python que inicia el servidor, por defecto `.venv/bin/python` con Make.

## Uso

1. Elegir un repositorio. Se preselecciona `default_repository` si existe; si no, el primero de la configuración.
2. Escribir una pregunta y pulsar **Consultar**.
3. Leer la respuesta y desplegar **Evidencias**, **Limitaciones** o **Estado del índice**.

El selector equivale a `--repo`: establece explícitamente el repositorio. No es necesario escribir el argumento dentro de la pregunta. Los límites de recuperación y contexto, la selección del modelo y las comprobaciones del índice se heredan de `coderag answer`; el chat no amplía la cobertura ni garantiza recuentos exhaustivos.

La respuesta se muestra como texto conservando sus saltos de línea, sin ejecutar HTML ni interpretar Markdown. Las evidencias conservan el contenido recuperado, archivo, líneas, certeza y distinción entre fuente citada y contexto. Se señala cuando un fragmento está truncado. Si las fuentes han cambiado, el estado muestra la necesidad de actualización y la orden incremental sugerida; no reconstruye índices automáticamente.

Para proveedores remotos, activar **Permitir enviar evidencias al proveedor remoto configurado** antes de consultar. Esto transmite `--allow-remote` a `answer`; no cambia de proveedor ni de modelo. Ollama mantiene el comportamiento de la CLI con la URL configurada.

Los errores de configuración, índices o proveedor se muestran en la conversación. Si el proceso no devuelve un error JSON legible, el chat ofrece un mensaje genérico sin exponer stderr. Para diagnosticar:

```bash
make doctor
make check-provider
```

## Historial y ejecución

Esta primera versión conserva el historial solo en memoria de la pestaña. **Las preguntas son independientes:** no se envían mensajes anteriores al modelo. Para una pregunta de seguimiento, incluir el contexto necesario en el propio texto. Recargar, cerrar la pestaña o pulsar **Nueva conversación** elimina el historial visible; este botón no modifica los índices.

El servidor admite una consulta activa a la vez y devuelve un aviso si otra pestaña intenta consultar simultáneamente. No hay streaming ni cancelación desde el navegador. Cerrar la pestaña no cancela una consulta en curso; esta termina o agota su tiempo máximo. El proceso hijo vuelve a cargar los recursos en cada pregunta, igual que una llamada independiente a la CLI.

El servidor lee `config.json` al listar repositorios y ejecutar consultas. Tras cambiar la lista de repositorios, recargar la página. Los cambios de proveedor y límites se aplican a la siguiente consulta.

## Acceso local

El servidor escucha exclusivamente en `127.0.0.1`, valida Host y Origin y requiere un token de sesión para las API. No expone rutas arbitrarias del sistema de archivos ni la configuración completa. Los recursos de la interfaz se incluyen en el paquete Python y no cargan servicios externos. Las preguntas y respuestas no se guardan en un historial del chat ni se registran en su log HTTP; el proveedor conserva su propia política de tratamiento de datos.

Está pensado para uso personal en el equipo local, sin autenticación de usuarios, publicación en red ni acceso multiusuario. La protección de sesión restringe peticiones desde otros orígenes del navegador; no a procesos del mismo usuario que puedan abrir la página local.

## Preguntas sobre flujos (0.9.21)

Se puede preguntar «¿Cuál es la primera función al llegar una petición?», concretar «Flujo de la petición POST /orders» o pedir «Flujo desde NOMBRE». Cuando se reconoce esta intención, `answer` prioriza entradas candidatas y sus llamadas estáticas. El panel **Flujo estático del código** muestra relaciones apoyadas por las evidencias incluidas; no una traza de ejecución. Ver [alcance, preparación y límites del análisis](code-rag-flujos.md).

## Identidad visual (0.9.22)

La cabecera integra el logo CodeTrace para fondos claros de `img/codetrace-logo-light.svg`. Su copia en `src/coderag/web/` se distribuye con el paquete Python y se sirve localmente, sin recursos externos. Al actualizar ese logo, sincronizar ambos archivos. El tamaño se adapta al ancho disponible en escritorio y móvil.

## Nombre del proyecto (0.9.23)

El proyecto y el chat utilizan la marca **CodeTrace**, y el paquete se llama `code-trace`. El comando público es `code-trace` y el módulo es `codetrace`; el módulo anterior `coderag` sigue siendo compatible. Ver [instalación y compatibilidad](code-trace.md).
