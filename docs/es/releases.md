# Publicaciones mediante etiquetas

[English](../en/releases.md)

Una etiqueta identifica un commit exacto. Un GitHub Release añade notas y, si corresponde, archivos descargables. La publicación de paquetes y el despliegue dependen de la automatización del proyecto.

```text
feature/* → PR → dev → PR de promoción → main → CI correcto → v1.2.0 → GitHub Release
```

## Permisos

La persona responsable coordina las publicaciones estables. El script de configuración protege las ramas de forma predeterminada. Para controlar la creación, actualización y eliminación de etiquetas, se puede aplicar una regla independiente a `v*`. Revisar los permisos de escritura del repositorio y mantener las contribuciones externas mediante forks y PR a `dev`. Las [publicaciones inmutables](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases) protegen la etiqueta y sus adjuntos mientras existe la publicación.

## Preparar una versión estable

Usar etiquetas `vMAJOR.MINOR.PATCH` según [Semantic Versioning](https://semver.org/). Incrementar MAJOR ante cambios incompatibles, MINOR ante funcionalidades compatibles y PATCH ante correcciones compatibles. El prefijo `v` va en la etiqueta.

1. Crear una rama como `release/1.2.0` desde `dev` y actualizar versión, lockfiles pertinentes y changelog.
2. Abrir un PR a `dev` y fusionarlo tras las revisiones y comprobaciones requeridas.
3. Promover `dev` a `main` mediante PR y esperar a que la CI del commit resultante termine correctamente. Guardar el SHA completo de ese commit.
4. Mantener `dev` como rama permanente y conservar el historial compartido entre promociones con commits de merge.

## Etiquetar y publicar manualmente

Desde el repositorio correcto, comprobar el remoto y revisar el commit exacto:

```sh
git remote -v
git status --short
git fetch origin main --tags
release_commit=PASTE_VERIFIED_MAIN_COMMIT_SHA
git show --no-patch --format=fuller "$release_commit"
git merge-base --is-ancestor "$release_commit" origin/main
```

Si la comprobación de ascendencia falla, detenerse. Verificar la versión y CI para el SHA antes de crear la etiqueta anotada:

```sh
git tag -a v1.2.0 "$release_commit" -m "Release v1.2.0"
git show v1.2.0
git push origin refs/tags/v1.2.0
```

La CI incluida se ejecuta para ramas y PR. La etiqueta se publica después de verificar CI en el commit.

```sh
gh release create v1.2.0 \
  --repo YOUR_USER/YOUR_REPOSITORY \
  --verify-tag \
  --title 'v1.2.0' \
  --generate-notes \
  --draft
```

`--verify-tag` exige que la etiqueta exista en el remoto. Revisar notas, rango de comparación, instrucciones de migración y adjuntos construidos desde el commit etiquetado antes de publicar el borrador. Las notas generadas no actualizan el changelog. Para fijar el inicio de la comparación, añadir `--notes-start-tag v1.1.0` cuando exista una publicación anterior.

## Versiones preliminares y correcciones

Para una candidata, usar una etiqueta distinta, como `v1.3.0-rc.1`, en un commit verificado de `dev`. Comprobar ascendencia respecto a `origin/dev` y añadir `--prerelease` al crear el borrador. La versión estable se etiqueta aparte tras la promoción a `main`.

Si una publicación necesita corregirse, conservar la etiqueta publicada y publicar una nueva versión. La ruta habitual pasa por `dev` y después por `main`. Para una corrección urgente cuando `dev` contiene cambios pendientes, crear `hotfix/1.2.1` desde `main`, abrir PR a `main`, verificar y etiquetar el commit resultante, y sincronizar la corrección con `dev` mediante PR. Un rollback operativo sigue el procedimiento de despliegue del proyecto.

## Publicación automatizada

[release.json](../../release.json) configura la versión de `pyproject.toml` y los comandos de test. La automatización también admite archivos de versión simples y manifiestos npm. Si se usa npm, declarar tanto `package.json` como `package-lock.json`. `test` y `package` contienen comandos como listas de argumentos. Los patrones de `assets` deben encontrar archivos con nombres base únicos.

1. Añadir notas en la primera sección `## Unreleased` de `CHANGELOG.md`. También se admite `## 1.1.0 (Unreleased)`.
2. Para una versión menor o mayor, preparar la versión de desarrollo correspondiente en `dev`, por ejemplo `1.1.0-dev.0` o `2.0.0-dev.0`.
3. Fusionar un PR del `dev` del mismo repositorio a `main` con **Create a merge commit**. Un job de solo lectura construye y prueba el commit estable. Otro job usa la App para publicar de forma atómica el commit y su etiqueta, crear el release con sus adjuntos y avanzar `dev` al próximo ciclo de parche.

Si falla, relanzar el workflow original. Una etiqueta existente debe apuntar al commit estable de esa promoción. El workflow retoma el borrador o verifica la publicación existente. Si `dev` avanzó por separado, sincronizar el commit estable y actualizar versión y changelog mediante PR revisado. Completar esa sincronización antes de iniciar otra promoción.

Consultar [etiquetas anotadas de Git](https://git-scm.com/docs/git-tag) y [creación de releases con GitHub CLI](https://cli.github.com/manual/gh_release_create).
