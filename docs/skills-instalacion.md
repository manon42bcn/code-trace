# Instalación de skills

Las instalaciones declaradas en `skills.installations` del `config.json` de CodeTrace se gestionan con:

```bash
make skills-install SKILL_ARGS="--dry-run"
make skills-install
make skills-status
make skills-update
```

Cada entrada define `destination` (directorio padre), `repo` (repositorio por defecto) y `names` (skills seleccionadas). Las rutas relativas se resuelven desde el directorio de `config.json`. El registro local generado es `skills/installations.local.json`.

Desde la versión 0.9.13, las copias instaladas incluyen de nuevo `config.example.json` como archivo gestionado y versionable en el repositorio consumidor. `make skills-update` lo sincroniza con el original de CodeTrace y lo restaura si una instalación anterior lo había omitido.

El instalador también genera `config.local.json`, que queda excluido de Git por el `.gitignore` de cada skill. Al clonar el repositorio consumidor, cada persona puede copiar `config.example.json` como `config.local.json` y ajustar su ruta de CodeTrace y repositorio por defecto.

Las modificaciones locales al ejemplo bloquean la actualización hasta su revisión, como ocurre con el resto de archivos gestionados. Sincronizar el ejemplo no cambia la configuración local; esta conserva las reglas de gestión declarativa o instalación puntual correspondientes.

No se desinstalan copias al eliminar entradas de la configuración. Los argumentos explícitos `--dest` mantienen el modo de instalación puntual, que conserva las configuraciones locales existentes.

## Nombres y configuración

Las skills se distribuyen como **code-trace** y **code-trace-inventory**. Usan el Python de `.venv` del checkout para ejecutar `python -m codetrace answer` y `python -m codetrace query --mode evidence`, respectivamente. La primera devuelve la respuesta del modelo de CodeTrace literalmente; la segunda entrega evidencias al agente consumidor para que las interprete.

Una declaración actualizada tiene esta forma:

```json
{
  "skills": {
    "installations": [
      {
        "destination": "../aicc-tests/.claude/skills",
        "repo": "aicc-tests",
        "names": ["code-trace", "code-trace-inventory"]
      }
    ]
  }
}
```

Las instalaciones se gestionan directamente con `skills-install`, `skills-update` y `skills-status`. `--skill code-trace` o `--skill code-trace-inventory` seleccionan una sola. Las declaraciones y el registro deben utilizar los nombres actuales.

Las conexiones nuevas y los ejemplos usan `code_trace_root` y `repo`. Se acepta `code_rag_root` como alias de compatibilidad; si ambos campos están presentes deben resolver al mismo checkout.

El perfil de recuperación se llama `query_profiles.code-trace-inventory`. El launcher sigue utilizando `query_profiles.code-inventory` cuando solo existe el perfil anterior, para conservar los presupuestos configurados. Si existen ambos, prevalece el nuevo.

Invocar `/code-trace` o `/code-trace-inventory`. Si el agente no actualiza su listado, recargar su ventana o iniciar una sesión nueva.
