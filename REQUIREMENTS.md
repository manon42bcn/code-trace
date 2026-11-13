# Local setup requirements

Install Python 3.13 or newer, Git, and [GitHub CLI](https://cli.github.com/).
The configurator uses the Python standard library.

## GitHub credentials

Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new)
for the target repository. Choose its owner as **Resource owner** and select
only that repository. The authenticated user needs repository admin access.

The following fine-grained token permissions were validated for the full local setup.

| Repository permission | Access |
| --- | --- |
| Administration | Read and write |
| Actions | Read and write |
| Contents (code) | Read and write |
| Workflows | Read and write |
| Metadata | Read-only, included automatically |

For automated releases, also grant repository **Secrets: Read and write**
and **Variables: Read and write** to the local token. The release App itself
uses **Contents: Read and write**.

Set `GH_TOKEN` in the shell running the script, or authenticate with
`gh auth login --hostname github.com` and use the stored session. No environment
variable is required with a working stored session. An exported `GH_TOKEN`
takes precedence. Load it from your local secret store and keep it out of the
repository and shell history.

Verify access using the same shell:

```sh
gh api repos/OWNER/REPOSITORY --jq '.permissions.admin'
gh api 'repos/OWNER/REPOSITORY/actions/runs?per_page=1' --jq '.total_count'
```

The first command should return `true`. The second should return a count.
For a private repository, check that your GitHub plan supports repository
rulesets.

Branch initialization needs a remote `main`. If GitHub returns HTTP 403 when creating
`dev`, verify Contents and Workflows write access on the token used by the
command. Make uses `GH_ADMIN_TOKEN` when it is set and nonempty.

The inputs below apply to ruleset preview and apply.

## Repository inputs

- Both `main` and `dev` exist on GitHub and share history.
- Both branch heads contain the generated `.github/CODEOWNERS` for the
  individual account passed as `--merger`. That account needs write access.
- Each required `--check` is a unique GitHub Actions job name and has succeeded
  on a push run for the current head of each branch. Include your project's
  CI jobs where applicable.
- For optional release automation, have the numeric GitHub App ID ready for
  `--release-app-id`. Install the App on the target repository and configure
  its workflow credentials in GitHub Actions. These credentials are separate
  from the local token.

Follow the setup guide in `docs/repository-setup.md` before cleanup to preview the rulesets
before applying them.

## Configurator defaults

Run `python3 scripts/configure_repository.py` to preview. The script detects
the GitHub repository from the checkout's `origin`, including SSH aliases
that resolve to github.com. It uses `manon42bcn` as merger and requires
`Repository checks`. Confirm the target before adding `--apply`.

Override these values with `--repo`, `--merger`, and `--check`. Explicit
`--check` arguments replace the default list. Repeat the flag for each
required job, including `Repository checks` if you want to retain it.

## Setup with Make

Run `make init` from the new checkout. It creates `dev`, waits for CI on both
branches and applies the rulesets. To enable automated releases, follow the
[release setup guide](docs/release-automation.md) and set
`RELEASE_AUTOMATION_ENABLED=true` in your local `.env`.

Provide `GH_ADMIN_TOKEN` through your environment or `.env` to pass it to
GitHub CLI as `GH_TOKEN`. Otherwise, GitHub CLI uses its normal credentials.
Make defaults to `pyenv exec python`. To select a Python installation, use
`PYENV_VERSION=3.13.0 make init` or set `PYTHON`.

After setup succeeds, run `make clean-template` in the same checkout. CI and
the default release configuration both call `sh scripts/test.sh`.
