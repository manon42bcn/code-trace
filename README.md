# Python repository starter

Develop on branches from `dev` and merge their pull requests back into `dev`.
Promote `dev` to `main` with a merge commit.

## Python development

Create a virtual environment with Python 3.13 or newer.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade "pip>=25.1"
python -m pip install --group dev
pre-commit install
```

Run `ruff check .` for linting and `ruff format --check .` to verify formatting.
Run `pre-commit run --all-files` to apply Ruff fixes and formatting and validate
JSON. Update `project.name` in `pyproject.toml` for your new repository.

Run `sh scripts/test.sh` locally. CI runs Ruff before this command, which
the default release configuration also uses. Replace the smoke checks in `scripts/test.sh` with your project's tests.

See the [manual release guide](docs/releases.md) or the
[automated release guide](docs/releases.md#automated-releases).

Follow the [quick setup guide](STEP_GUIDE.md) before cleaning the checkout.
Run `make init` for either release mode. Omit `.env` or set
`RELEASE_AUTOMATION_ENABLED=false` for manual releases. Set it to `true`
after configuring the App to enable automated releases.

After setup succeeds, run `make clean-template`. It removes the setup files,
including this README and the Makefile. After automated setup it also removes
the local `.env`.
