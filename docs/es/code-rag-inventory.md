# Inventarios de CodeTrace: CLI independiente

[English](../en/cli-inventory.md)

`codetrace inventory` realiza conteos estructurales sobre las instantáneas indexadas, sin llamar al LLM. Es una operación explícita de la CLI y no un modo de la skill `/code-trace`, que utiliza siempre `answer`.

Para contar entradas de una lista YAML/JSON conocida:

```bash
.venv/bin/python -m codetrace inventory --config config.json --repo demo \
  --file accounts.json \
  --path '$/accounts' --unique-by username
```

El total se calcula para ese alcance completo antes de paginar la salida. `--where CAMPO=VALOR` filtra valores escalares exactos; `--group-by CAMPO` agrupa. `--unique-by` agrupa identidades preservando sus apariciones. No se comprueba el registro ni la ejecución de herramientas en tiempo real.

La pregunta de texto solo puede servir para seleccionar el repositorio cuando se usa `--default-repo`; no filtra listas semánticamente por palabras como `handoff`. Sin un alcance único, se devuelven listas candidatas (`needs_scope`), no fuentes relevantes para una pregunta de comportamiento. El orden de ese catálogo no es un ranking de recuperación.

Para contar funciones con un decorador Python escrito explícitamente en un archivo indexado:

```bash
.venv/bin/python -m codetrace inventory --config config.json --repo demo_library \
  --kind python-decorators --file features/steps/common.py \
  --decorator given
```

Se analiza AST sin importar ni ejecutar código. Se incluyen funciones anidadas y async; múltiples decoradores coincidentes de una función no multiplican el número de funciones. Los alias, expresiones dinámicas y registros condicionales no quedan resueltos. Los índices deben contener las instantáneas completas necesarias; una instantánea ausente exige preparación y no se sustituye por leer archivos actuales.
