# Optional release automation

Use the included release workflow to publish stable versions from promotion PRs
from `dev` to `main`. For projects that publish manually, follow the
[manual release guide](releases.md).

## Initialize a repository

1. [Create the repository from the template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
   with **Include all branches** unchecked. Clone it locally.
2. Install MyAuto Release on the new repository with **Contents: Read and write**.
   Keep its private key outside the checkout. Authenticate GitHub CLI with an
   administrator credential with access to the target repository.
   If using a fine-grained token, also grant **Secrets: Read and write** and
   **Variables: Read and write** for this repository.
3. Copy `.env.example` to `.env` and fill in the numeric App ID, the App Client ID,
   and the path to the private key. Set `RELEASE_MERGER` to the username that owns
   and merges changes. If the username differs from the one in the committed
   CODEOWNERS, regenerate it using `--prepare-codeowners --merger YOUR_USER`
   and push it to `main`. Commit any changes to the project adapter too.
4. Run `make init`. Make sources your local `.env` as shell code. The
   initializer creates `dev` from `main`, opens the first development version,
   and waits for CI on both branches. It stores the App key as an Actions secret,
   applies and verifies the managed rulesets, and enables the release workflow
   by setting `RELEASE_AUTOMATION_ENABLED` to `true` in GitHub Actions. It also
   enables merge commits and turns off automatic branch deletion.
5. After success, run `make clean-template` to remove the setup files and the
   local, untracked `.env`. The initializer removes its temporary checkout automatically. The
   original PEM stays at the path you provided.

The initializer uses the checkout's `origin`. It needs no previous tag and
leaves an existing `dev` in place if its development version, changelog and
CODEOWNERS are ready. If the command fails, retain `.env`, correct the issue and
rerun it. If CI takes longer than ten minutes, rerunning uses the existing
branch. If inherited rules prevent creation of `dev` or direct writes or tag
creation by the App, configure those rules with their administrator. The
managed App bypass applies to branch rules and tag creation. Tag updates and
deletions remain blocked by a separate ruleset.

## Configure a project

The default `release.json` uses `[project].version` in `pyproject.toml` and runs `sh scripts/test.sh`. Keep the version as a quoted string on its own line under `[project]`. Plain version files and npm manifests are also supported.
When using npm, list both `package.json` and `package-lock.json` to update and
validate their versions together. The `test` and optional `package` arrays
contain commands as argument lists. The optional `assets` array contains
relative globs, each of which must match at least one file. Asset basenames
must be unique.

For Toolium, copy `examples/release-toolium.json` from the template before cleanup
and install the
project's Node version in the workflow's prepare job before running the script.
The adapter runs `npm ci`, `npm test` and `npm run package`, and attaches
`dist/*.vsix`. Visual Studio Marketplace publication is manual.

If you replace the default CI job, pass the required job names to the
initializer, for example `make init RELEASE_INIT_ARGS='--check "Test and package"'`.
The configurator requires successful **push** checks on both branch tips.
Replace `scripts/test.sh` with your project checks when ready.

## Publish and retry

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

To test in a disposable repository, start from a default branch with no tags.
Verify the initial dev version, a promotion and its tag, and the next version
on dev. Re-run the same promotion after publication and confirm that the tag
and GitHub Release stay the same. Test an interrupted draft and a dev branch
that advances during publication before using the workflow in production.
