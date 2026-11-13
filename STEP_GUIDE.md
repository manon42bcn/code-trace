# Configurar un repositorio desde el template

1. En GitHub, usa **Use this template** con **Include all branches** desmarcado. Clona el repositorio nuevo y comprueba el destino con `git remote get-url origin`.
2. Selecciona Python 3.13 o superior en pyenv. Si tienes instalada la versión 3.13.0, ejecuta `export PYENV_VERSION=3.13.0`. Carga el token fine-grained en `GH_ADMIN_TOKEN` o usa tu sesión de `gh`. [Permisos del token](REQUIREMENTS.md)
3. Comprueba que `.github/CODEOWNERS` identifica al mantenedor. Para releases manuales, omite `.env` o usa `RELEASE_AUTOMATION_ENABLED=false`. Para releases automáticas, instala la App y prepara el `.env` siguiendo la [guía de alta](docs/release-automation.md).
4. Ejecuta `make init`. Crea `dev`, espera a CI y aplica las reglas en GitHub.
5. Configura el entorno de desarrollo y los hooks siguiendo el [README](README.md#python-development). Actualiza el nombre del proyecto en `pyproject.toml`.
6. Para retirar los archivos de alta, ejecuta `make clean-template` y revisa las eliminaciones antes de incluirlas en un PR desde una rama de limpieza a `main`. Después sincroniza `main` en `dev` mediante un PR. Sustituye el contenido de `scripts/test.sh` cuando tengas tests del proyecto.

## Si algo falla

| Síntoma | Qué revisar |
| --- | --- |
| Python incorrecto | Ejecuta `pyenv exec python --version` y selecciona una versión compatible. |
| HTTP 401 o 404 | Comprueba que la credencial esté vigente, que tenga acceso al repositorio y que `origin` apunte al clon correcto. |
| HTTP 403 al crear `dev` | Revisa el acceso de escritura a **Contents** y **Workflows** en el token activo. |
| HTTP 403 al aplicar rulesets | Revisa el acceso de escritura a **Administration**. La autenticación por sí sola confirma la identidad. |
| HTTP 403 al configurar secretos o variables | Para releases automáticas, el token personal necesita **Secrets** y **Variables** con permiso de lectura y escritura. |
| CI pendiente, fallido o ausente | En **Actions**, revisa la ejecución de tipo `push` del commit actual de la rama indicada por el script. |
| La limpieza se detiene | Completa `make init` en ese clon antes de limpiar. |
