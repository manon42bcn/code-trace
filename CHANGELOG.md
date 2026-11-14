# Changelog

Historial de cambios de CodeTrace (`code-trace`), anteriormente Code RAG. Las entradas 0.9.0–0.9.25 se han reconstruido a partir de los commits y de la versión declarada en `pyproject.toml`. Las fechas corresponden al commit que introduce cada versión; no presuponen una publicación en un registro de paquetes. Para etapas anteriores a 0.9.0, consultar el historial Git.

## 0.9.26 — 2026-11-09

- Añadido README con instalación local, configuración, CLI, chat, skills, mantenimiento y límites actuales.
- Añadido este CHANGELOG con el historial verificable de versiones 0.9.x y la pauta para mantenerlo actualizado.

## 0.9.25 — 2026-11-09

- Eliminados `make skills-migrate`, el comando de migración del instalador, el soporte de nombres antiguos en declaraciones/registros y su documentación.
- El instalador utiliza los nombres `code-trace` y `code-trace-inventory` y las operaciones `install`, `update` y `status`.

## 0.9.24 — 2026-11-09

- Renombradas las skills a `code-trace` y `code-trace-inventory`; sus lanzadores utilizan `python -m codetrace` con el entorno del checkout.
- Añadido `code_trace_root` a conexiones y ejemplos, con aceptación del campo anterior `code_rag_root`.
- Actualizado el perfil de evidencias a `code-trace-inventory`, con soporte del perfil anterior.
- Incorporada una herramienta de migración de instalaciones registradas, retirada en 0.9.25.

## 0.9.23 — 2026-11-09

- Renombrado el proyecto y el paquete a `code-trace`, con marca CodeTrace.
- Añadidos el comando instalable `code-trace` y el módulo `codetrace`, conservando el módulo `coderag`.
- Actualizados Makefile, interfaz, documentación y textos de las skills.

## 0.9.22 — 2026-11-09

- Integrado el logo CodeTrace en la cabecera del chat, con adaptación a escritorio y móvil.
- Incluido el recurso SVG en el paquete Python y actualizado el título de la pestaña.

## 0.9.21 — 2026-11-09

- Añadido análisis específico para preguntas sobre flujos, handlers HTTP de FastAPI/Flask y símbolos Python de inicio.
- Priorizadas evidencias estructurales y llamadas estáticas acotadas, conservando los presupuestos de contexto.
- Añadido un panel de flujo en el chat y una sección en la salida con evidencias, con advertencias de ambigüedad y límites estáticos.

## 0.9.20 — 2026-11-09

- Añadidos el chat web local, `make chat` y el subcomando `chat`, sin Docker ni dependencias web adicionales.
- Incorporados selector de repositorio, respuesta literal del proveedor, evidencias desplegables y estado del índice.
- Añadidos control de errores y acceso limitado a localhost; historial temporal en la pestaña con preguntas independientes.

## 0.9.19 — 2026-11-06

- Mejorados los avisos del parser Python para conservar archivo, línea original, categoría y mensaje.
- Persistidos los diagnósticos en los índices y conservados durante la reutilización incremental.
- Evitadas emisiones duplicadas con ubicaciones locales o `<unknown>` en análisis derivados.

## 0.9.18 — 2026-11-06

- Retirado `config.json` del seguimiento y añadido a `.gitignore`.
- Renombrada la plantilla central a `config.example.json` y actualizada la documentación de configuración local.

## 0.9.17 — 2026-11-06

- Registrada la referencia Git de la última indexación: commit, rama y estado de cambios locales.
- Añadidas comprobaciones de frescura en diagnóstico, consultas y respuestas, diferenciando cambios de referencia y de fuentes indexables.
- Mostrado el estado del índice y la orden incremental sugerida, sin reconstrucción ni acceso remoto Git automáticos.

## 0.9.16 — 2026-11-05

- Restringida la skill de respuestas a `answer`, sin selección automática de inventario o evidencias.
- Preservados el modelo, proveedor y presupuestos centrales; añadida resolución de routing sin generación para diagnóstico.

## 0.9.15 — 2026-11-05

- Mejorado el tratamiento de selectores explícitos de repositorio y de cláusulas de alcance en preguntas naturales.
- Ajustado el ranking para favorecer cobertura de términos relevantes frente a coincidencias aisladas de metadatos.
- Reforzadas las instrucciones de idioma, relevancia de citas e insuficiencia de evidencia; añadidos casos de evaluación de relevancia.

## 0.9.14 — 2026-11-05

- Añadidos perfiles centrales de presupuesto para la skill de evidencias, independientes de la generación.
- Permitidos límites específicos de candidatos, chunks, caracteres y tokens, con conservación del perfil durante la paginación.

## 0.9.13 — 2026-11-05

- Restaurada la distribución de `config.example.json` en las skills instaladas para versionar y sincronizar el ejemplo en los repositorios consumidores.
- Mantenida la separación respecto de `config.local.json`.

## 0.9.12 — 2026-11-05

- Excluida temporalmente la plantilla de configuración de las instalaciones de skills; comportamiento revertido en 0.9.13.

## 0.9.11 — 2026-11-05

- Centralizadas las instalaciones deseadas de skills en `config.json` mediante destino, repositorio y nombres.
- Conservado el registro local de instalaciones y añadido seguimiento de diferencias en configuraciones gestionadas.

## 0.9.10 — 2026-11-05

- Añadidas comprobaciones de preparación de consultas para índices, relaciones, vectores y frescura de las fuentes.
- Incorporados diagnósticos de readiness y opciones de comprobación de fuentes actuales.

## 0.9.9 — 2026-11-05

- Añadidas sesiones locales acotadas para continuar consultas sin repetir la recuperación ni cargar los modelos en cada página.
- Incorporadas validación de artefactos, caducidad y límites de almacenamiento de sesiones.

## 0.9.8 — 2026-11-05

- Incorporado un plan local de recuperación para preguntas en lenguaje natural, con términos, variantes e identificadores ancla.

## 0.9.7 — 2026-11-05

- Mejorado el ranking de consultas y la ordenación de coincidencias de código.

## 0.9.6 — 2026-11-05

- Añadidos filtros de fuentes por archivo, directorio y tipo, aplicados antes de los límites de recuperación.

## 0.9.5 — 2026-11-05

- Automatizadas la instalación, actualización y consulta de estado de ambas skills.
- Añadidos registro local de instalaciones, hashes de archivos gestionados y protección frente a cambios locales.

## 0.9.4 — 2026-11-05

- Ampliado el inventario de estructuras compatibles y sus operaciones de selección, filtrado y agrupación.

## 0.9.3 — 2026-11-05

- Añadida una batería pequeña de preguntas reales y herramientas de evaluación de recuperación.

## 0.9.2 — 2026-11-05

- Incorporada continuación de búsquedas mediante paginación y cursores.

## 0.9.1 — 2026-11-04

- Explicitados los límites de recuperación y selección de evidencias en la salida de `query`.

## 0.9.0 — 2026-11-04

- Añadido `coderag doctor` para diagnosticar la preparación de los repositorios y orientar la resolución de problemas.
