# CodeTrace · code-trace (0.9.23)

El proyecto se llama **code-trace**, con la identidad visual **CodeTrace**. El paquete Python se distribuye como `code-trace` y ofrece el comando `code-trace` y el módulo `codetrace`.

## Instalación y uso

Actualizar el entorno del proyecto para registrar el nuevo comando:

```bash
make setup
.venv/bin/code-trace --help
```

El módulo se puede ejecutar con el Python del entorno:

```bash
.venv/bin/python -m codetrace --help
.venv/bin/python -m codetrace doctor --config config.json
make chat
```

También se puede usar `uv run --no-sync code-trace --help` desde el checkout con las dependencias necesarias instaladas. Para arrancar el chat desde la CLI:

```bash
.venv/bin/code-trace chat --config config.json
```

Consultar [la preparación](code-rag-preparacion.md), [el chat local](code-rag-chat.md), [los flujos estáticos](code-rag-flujos.md) y [la instalación de skills](skills-instalacion.md).

## Compatibilidad de la instalación existente

El módulo `coderag` y sus imports siguen disponibles. Los scripts, los lanzadores de las skills y los identificadores de formatos existentes siguen funcionando con las mismas configuraciones y artefactos.

Las skills se llaman `code-trace` y `code-trace-inventory`, usan `python -m codetrace` y las configuraciones nuevas incluyen `code_trace_root`. Las conexiones existentes con `code_rag_root` siguen admitidas. Se gestionan con `make skills-install`, `make skills-update` y `make skills-status`; ver [la guía de instalación](skills-instalacion.md).

No se mueve el checkout local ni se modifica `config.json`. Si se cambia manualmente el nombre de su directorio, habrá que actualizar las rutas absolutas que lo referencian, incluidas las conexiones de las skills y los entornos virtuales. Los archivos de documentación que conservan `code-rag` en el nombre mantienen sus enlaces existentes.
