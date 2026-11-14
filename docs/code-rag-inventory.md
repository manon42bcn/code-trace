# Inventarios de CodeTrace: CLI independiente

`coderag inventory` realiza conteos estructurales sobre las instantáneas indexadas, sin llamar al LLM. Es una operación explícita de la CLI y no un modo de la skill `/code-rag`, que utiliza siempre `answer`.

Para contar entradas de una lista YAML/JSON conocida:

```bash
.venv/bin/python -m codetrace inventory --config config.json --repo fabrica \
  --file eval/aedg/config/domains/parcelamento/agents/parcelamento_agent.yaml \
  --path '$/agent/tools' --unique-by tool_name
```

El total se calcula para ese alcance completo antes de paginar la salida. `--where CAMPO=VALOR` filtra valores escalares exactos; `--group-by CAMPO` agrupa. `--unique-by` agrupa identidades preservando sus apariciones. No se comprueba el registro ni la ejecución de herramientas en tiempo real.

La pregunta de texto solo puede servir para seleccionar el repositorio cuando se usa `--default-repo`; no filtra listas semánticamente por palabras como `handoff`. Sin un alcance único, se devuelven listas candidatas (`needs_scope`), no fuentes relevantes para una pregunta de comportamiento. El orden de ese catálogo no es un ranking de recuperación.

Para contar funciones con un decorador Python escrito explícitamente en un archivo indexado:

```bash
.venv/bin/python -m codetrace inventory --config config.json --repo aicc-tests \
  --kind python-decorators --file acceptance/common/steps/agent_evaluator/api.py \
  --decorator step
```

Se analiza AST sin importar ni ejecutar código. Se incluyen funciones anidadas y async; múltiples decoradores coincidentes de una función no multiplican el número de funciones. Los alias, expresiones dinámicas y registros condicionales no quedan resueltos. Los índices deben contener las instantáneas completas necesarias; una instantánea ausente exige preparación y no se sustituye por leer archivos actuales.
