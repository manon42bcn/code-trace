# Releases through tags

The default manual release process works with any project
language. A tag identifies an exact commit; a GitHub Release adds release notes
and optional downloadable assets. Neither operation deploys an application or
publishes a package unless the project adds its own automation.

```text
feature/* → PR → dev → promotion PR → main → successful CI → v1.2.0 → GitHub Release
```

The designated maintainer coordinates stable releases. The configuration script
protects branches only in its default configuration: it does not restrict tag creation, updates or deletion,
and it does not enforce this release sequence. Add a separate tag ruleset for
`v*` if you need to enforce who creates tags and prevent changes to published tags.

For automated releases, see [the workflow instructions](#automated-releases).

## Release permissions

Reserve write access to the upstream repository for the owner. GitHub users with
write access can create, edit and delete releases. Contributors work from forks
and submit PRs to `dev`. Review direct access, team access and installed apps
with write permissions in GitHub. The branch configuration script manages
rulesets, while repository access is configured separately.

You can also enable
[immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
to protect the published tag and attached files while the release exists.

## Choose and prepare a version

Use tags named `vMAJOR.MINOR.PATCH`, for example `v1.2.0`. Following
[Semantic Versioning](https://semver.org/), increment MAJOR for incompatible API
changes, MINOR for compatible features, and PATCH for compatible fixes. Define
what compatibility means for your project; versions before 1.0 indicate initial
development. The `v` prefix belongs to the tag, not the version number itself.

1. Start a preparation branch from `dev`, for example `release/1.2.0`.
2. Update the project's version files, relevant lockfiles, and changelog if used.
   Use the versioning commands appropriate for your project.
3. Open a PR to `dev`, wait for required checks and reviews, and have the designated
   maintainer merge it.
4. Open the promotion PR from `dev` to `main`. Review the complete release scope;
   the designated maintainer merges it once checks and review requirements pass.
5. Wait for all required CI jobs to pass on the resulting `main` commit. Record
   that exact commit SHA for tagging, even if `main` advances later.

Keep automatic head-branch deletion disabled for the permanent `dev` branch.
Merge commits help preserve shared history between repeated promotions.

## Create and push the tag

Run from the intended repository with a clean working tree. Replace the version,
repository name and commit placeholder throughout the examples. Confirm that
`origin` refers to the intended repository before pushing.

```sh
git remote -v
git status --short
git fetch origin main --tags

# Paste the full SHA of the main commit whose CI you verified.
release_commit=PASTE_VERIFIED_MAIN_COMMIT_SHA
git show --no-patch --format=fuller "$release_commit"
git merge-base --is-ancestor "$release_commit" origin/main
```

Stop if the ancestry check exits nonzero: the selected commit must be on `main`.
Confirm its version files and CI results, then create an annotated tag at that
explicit SHA. Do not rely on the currently checked-out branch or `HEAD`.

```sh
git tag -a v1.2.0 "$release_commit" -m "Release v1.2.0"
git show v1.2.0
git push origin refs/tags/v1.2.0
```

Push only the intended tag. A successful tag push does not certify CI and does
not trigger the included CI workflow, which runs on branch pushes and PRs.
Additional tag workflows, if added by a project, may run at this point.

## Publish a GitHub Release

Create a draft from the existing remote tag:

```sh
gh release create v1.2.0 \
  --repo YOUR_USER/YOUR_REPOSITORY \
  --verify-tag \
  --title 'v1.2.0' \
  --generate-notes \
  --draft
```

`--verify-tag` requires the remote tag to exist rather than letting the CLI create
one automatically. Open the draft in the repository's **Releases** page, review
its notes and comparison range, add migration instructions and attach any project
artifacts built from the tagged commit. Generated notes do not update a committed
changelog. Publish the draft after reviewing it; that is the release publication
step. Package publication and deployment remain project-specific.

For later releases, optionally add `--notes-start-tag v1.1.0` to select the
previous release explicitly. Omit it for the first release.

## Prereleases

For a release candidate, use a distinct tag such as `v1.3.0-rc.1` at a verified
commit and add `--prerelease` to the draft creation command. The recommended
prerelease path is a verified `dev` commit; use `git fetch origin dev --tags` and
check ancestry against `origin/dev` instead of `origin/main`. Check CI for that
exact commit and follow the same tag and draft review steps.

A stable release still goes through the promotion PR to `main` and receives its
own stable tag. Do not move a release-candidate tag to the final commit.

## Corrections and the next cycle

Treat published tags and versions as permanent. If a published release contains
a defect, make a fix through PRs, rerun checks, and publish a new version such as
`v1.2.1`; do not force-update or reuse `v1.2.0`.

The normal fix route is a branch from `dev`, a PR back to `dev`, then promotion
to `main`. If `dev` already contains changes that must not ship in an urgent fix,
branch `hotfix/1.2.1` from `main` and open a PR directly to `main`. The designated
maintainer merges after required checks and reviews. Tag the verified resulting
commit, then synchronize the fix from `main` into `dev` through a PR before the
next promotion. This exception is compatible with the branch rules, which do not
restrict PR source branches. Include version and changelog updates in the fix PR.

Begin the next normal cycle from `dev`. Deliver any next-development-version
updates through a PR rather than a direct push. If a deployment needs rollback,
follow the project's deployment procedure; moving a Git tag is not a rollback.

## Automated releases

### Configure the project

The default `release.json` uses `[project].version` in `pyproject.toml` and runs `sh scripts/test.sh`. Keep the version as a quoted string on its own line under `[project]`. Plain version files and npm manifests are also supported.
When using npm, list both `package.json` and `package-lock.json` to update and
validate their versions together. The `test` and optional `package` arrays
contain commands as argument lists. The optional `assets` array contains
relative globs, each of which must match at least one file. Asset basenames
must be unique.

For a VS Code extension that uses npm, configure the prepare job to install
the project’s Node version and set the package command and asset glob, for
example `npm run package` and `dist/*.vsix`. Publish to Marketplace manually.

### Publish and retry

1. Work from `dev` and merge changes back into it. Add release notes to the
   first `## Unreleased` section in `CHANGELOG.md`. The versioned form
   `## 1.1.0 (Unreleased)` is also accepted.
2. For a minor release, prepare `1.1.0-dev.0` in a PR to `dev`. For a major
   release, prepare `2.0.0-dev.0`. The next development versions after release
   are `1.1.1-dev.0` and `2.0.1-dev.0`, respectively.
3. Merge a PR from the same repository's `dev` to `main` using **Create a
   merge commit**. The workflow builds and tests the stable commit on a
   read-only runner. A separate job uses the App to push the stable commit and
   its tag atomically, publish the release with its assets, and fast-forward
   `dev` to the next patch cycle.

If a run fails, rerun the original workflow. The existing tag must point to
the stable commit for that promotion. The workflow resumes a draft or verifies
an already published release. If `dev` advanced independently, synchronize the
stable commit and update the version and changelog via a reviewed PR. Keep
promotion PRs sequential until the previous release has synchronized `dev`.

## References

- [Git annotated tags](https://git-scm.com/docs/git-tag)
- [GitHub CLI release creation](https://cli.github.com/manual/gh_release_create)
- [Semantic Versioning](https://semver.org/)
